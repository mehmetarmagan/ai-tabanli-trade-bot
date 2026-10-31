import asyncio
import logging
import os
import sys
from pathlib import Path

import structlog

def _configure_logging():
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CeoTrade" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "ceotrade.log", encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.KeyValueRenderer()],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()

from core.config import AppConfig, load_app_config
from core.data_engine import MarketDataEngine
from core.indicators import IndicatorEngine
from core.strategy import StrategyEngine
from core.risk_manager import RiskManager
from core.adapters.futures_adapter import BinanceFuturesAdapter
from core.adapters.paper_adapter import PaperTradingAdapter
from core.adapters.security.mode_guard import TradingModeGuard
from core.execution_engine import ExecutionEngine
from core.database import SignalDatabase
from core.signal_aggregator import SignalAggregator
from core.notifications import NotificationService
from core.secure_storage import SecureStorage

logger = structlog.get_logger()

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "SUI/USDT"
]
DEFAULT_TIMEFRAMES = ["15m", "1h"]


class CeoTradeOrchestrator:
    def __init__(
        self,
        symbols=DEFAULT_SYMBOLS,
        initial_balance=5000.0,
        timeframes=None,
        symbol_timeframes=None,
        config: AppConfig | None = None,
    ):
        self.config = config or load_app_config()
        self.symbols = list(symbols if symbols is not DEFAULT_SYMBOLS else self.config.symbols)
        self.timeframes = list(timeframes or self.config.timeframes)
        self.scan_interval_seconds = self.config.scan_interval_seconds
        self.scan_targets = self._build_scan_targets(symbol_timeframes=symbol_timeframes)

        self.market_data = MarketDataEngine()
        self.strategy = StrategyEngine(enable_short=True, require_rsi_recovery=False)
        self.risk_manager = RiskManager(total_balance=initial_balance)

        # Veritabanı Yöneticisini Başlat
        self.db = SignalDatabase()
        self.signal_aggregator = SignalAggregator()
        self.notifier = NotificationService(
            telegram_token=self.config.telegram_bot_token or SecureStorage.get_secret("telegram_bot_token"),
            telegram_chat_id=self.config.telegram_chat_id or SecureStorage.get_secret("telegram_chat_id"),
            whatsapp_number=self.config.whatsapp_number,
            whatsapp_webhook_url=self.config.whatsapp_webhook_url or SecureStorage.get_secret("whatsapp_webhook_url"),
        )
        self.notification_channel = self.config.notification_channel

        # Paper Trading ve Güvenlik Altyapısı
        self.mode_guard = TradingModeGuard({
            "LIVE_TRADING_ENABLED": self.config.live_trading_enabled,
            "TRADING_MODE": self.config.mode,
        })
        self.mode_guard.set_mode(self.config.mode)

        self.paper_adapter = PaperTradingAdapter(initial_equity_try=initial_balance)
        self.paper_adapter.connect()

        live_adapter = None
        if self.config.live_trading_enabled and self.config.mode == "live":
            live_adapter = BinanceFuturesAdapter(is_testnet=False, allow_live_orders=True)
            live_adapter.connect()

        self.live_adapter = live_adapter
        self.execution_engine = ExecutionEngine(
            paper_adapter=self.paper_adapter,
            live_adapter=self.live_adapter,
            mode_guard=self.mode_guard,
        )
        self.is_running = False

    def _build_scan_targets(self, symbol_timeframes=None):
        if symbol_timeframes:
            targets = []
            for item in symbol_timeframes:
                if isinstance(item, tuple) and len(item) == 2:
                    targets.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict):
                    symbol = item.get("symbol")
                    timeframe = item.get("timeframe")
                    if symbol and timeframe:
                        targets.append((str(symbol), str(timeframe)))
            if targets:
                return targets

        targets = []
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                targets.append((str(symbol), str(timeframe)))
        return targets

    def _build_signal_confidence(self, signal_result: dict, timeframe: str) -> float:
        action = str(signal_result.get("action", signal_result.get("signal", "HOLD"))).upper()
        if action == "HOLD":
            return 0.0

        confidence = 0.55
        rsi = signal_result.get("rsi")
        if isinstance(rsi, (int, float)):
            if action == "OPEN_LONG":
                confidence += max(0.0, (60.0 - abs(rsi - 50.0)) / 100.0)
            elif action == "OPEN_SHORT":
                confidence += max(0.0, (60.0 - abs(rsi - 50.0)) / 100.0)

        close = signal_result.get("close")
        ema_200 = signal_result.get("ema_200")
        if isinstance(close, (int, float)) and isinstance(ema_200, (int, float)) and ema_200 != 0:
            trend_gap = abs(float(close) - float(ema_200)) / abs(float(ema_200))
            confidence += min(trend_gap * 2.0, 0.25)

        time_weight = {"15m": 1.0, "1h": 1.2, "4h": 1.4, "1d": 1.6}
        confidence += time_weight.get(timeframe, 1.0) * 0.08
        return min(0.99, max(0.0, confidence))

    async def analyze_symbol(self, symbol: str, timeframe: str = "15m"):
        try:
            timeframe_results = []
            for current_timeframe in [timeframe] + [tf for tf in self.timeframes if tf != timeframe]:
                df = self.market_data.fetch_ohlcv(symbol=symbol, timeframe=current_timeframe, limit=250)
                if df is None or df.empty:
                    continue

                df_ind = IndicatorEngine.apply_all(df)
                if df_ind is None or df_ind.empty:
                    continue

                signal_res = self.strategy.evaluate_strategies(df_ind, current_position="FLAT")
                signal_action = signal_res.get("action", "HOLD")
                if signal_action != "HOLD":
                    confidence = self._build_signal_confidence(signal_res, current_timeframe)
                    timeframe_results.append({
                        "action": signal_action,
                        "timeframe": current_timeframe,
                        "confidence": confidence,
                        **signal_res,
                    })

            if not timeframe_results:
                return

            aggregated = self.signal_aggregator.aggregate(timeframe_results)
            action = aggregated.get("action", "HOLD")
            if action == "HOLD":
                return

            chosen_tf = aggregated.get("timeframes", [timeframe])[0]
            signal_payload = next(
                item for item in timeframe_results
                if item.get("timeframe") == chosen_tf and item.get("action") == action
            )
            last_row = signal_payload.get("last_row")
            if last_row is None:
                last_row = self.market_data.fetch_ohlcv(symbol=symbol, timeframe=chosen_tf, limit=1)

            if last_row is None or getattr(last_row, "empty", True):
                return

            if hasattr(last_row, "iloc"):
                last_row = last_row.iloc[-1]

            entry_price = float(last_row["close"])
            atr_value = float(last_row["ATR_14"]) if "ATR_14" in last_row and last_row["ATR_14"] > 0 else entry_price * 0.01

            direction = "BUY" if action == "OPEN_LONG" else "SELL"
            risk_plan = self.risk_manager.calculate_position_and_stop(
                entry_price=entry_price,
                atr_value=atr_value,
                direction=direction,
            )

            if risk_plan.get("approved"):
                stop_loss = risk_plan["stop_loss_price"]
                tp1 = risk_plan["tp1"]
                tp2 = risk_plan["tp2"]
                tp3 = risk_plan["tp3"]
                amount = risk_plan["position_size_units"]

                self.db.save_signal(
                    symbol=symbol,
                    action=action,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                )

                print(f"\n🚨 [SİNYAL YAKALANDI & KAYDEDİLDİ] Parite: {symbol} | Çerçeve: {chosen_tf} | Yön: {action} | Fiyat: {entry_price}")
                print(f"   Güven: {aggregated.get('confidence')} | Stop-Loss: {stop_loss:.4f} | TP1: {tp1} | Pozisyon Birimi: {amount:.4f}")
                self.notifier.send_signal_alert(
                    symbol=symbol,
                    action=action,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    tp1=tp1,
                    channel=self.notification_channel,
                )

                exec_res = self.execution_engine.execute_signal(
                    signal_result={"action": action},
                    symbol=symbol,
                    amount=amount,
                    price=entry_price,
                    stop_loss=stop_loss,
                    leverage=5.0,
                )
                print(f"   İşlem Sonucu: {exec_res.get('status')}\n")
            else:
                logger.warning("risk_plan_rejected", symbol=symbol, timeframe=chosen_tf, reason=risk_plan.get("error"))

        except Exception as e:
            logger.exception("symbol_analysis_error", symbol=symbol, timeframe=timeframe, error=str(e))

    def get_dashboard_summary(self):
        account = self.paper_adapter.get_account_summary()
        recent_signals = self.db.get_recent_signals(limit=5)
        return {
            "mode": self.mode_guard.trading_mode,
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "active_targets": len(self.scan_targets),
            "account": account,
            "recent_signals": recent_signals,
            "status": "RUNNING" if self.is_running else "IDLE",
        }

    def display_dashboard(self):
        summary = self.get_dashboard_summary()
        account = summary["account"]
        print("\n=== Ceo-Trade Dashboard ===")
        print(f"Mode: {summary['mode']} | Status: {summary['status']}")
        print(f"Symbols: {', '.join(summary['symbols'])}")
        print(f"Timeframes: {', '.join(summary['timeframes'])}")
        print(f"Open positions: {account.get('open_positions', 0)}")
        print(f"Available balance: {account.get('available_balance_try', 0.0)}")
        print(f"Reserved margin: {account.get('reserved_margin_try', 0.0)}")
        print("===========================\n")

    def start(self):
        if self.is_running:
            return False

        self.is_running = True
        print(f"🚀 Ceo-Trade Tarayıcı Başlatıldı! İzlenen Parite Sayısı: {len(self.scan_targets)}")
        self.display_dashboard()
        return True

    async def scan_loop(self):
        self.start()

        while self.is_running:
            tasks = [self.analyze_symbol(symbol, timeframe) for symbol, timeframe in self.scan_targets]
            await asyncio.gather(*tasks)
            if not self.is_running:
                break
            self.display_dashboard()
            for _ in range(max(1, self.scan_interval_seconds * 4)):
                if not self.is_running:
                    break
                await asyncio.sleep(0.25)

    def run(self):
        asyncio.run(self.scan_loop())

    def run_once(self):
        self.is_running = False
        results = []
        for symbol, timeframe in self.scan_targets:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.analyze_symbol(symbol, timeframe))
                results.append({"symbol": symbol, "timeframe": timeframe, "status": "processed"})
            except Exception as exc:  # pragma: no cover - defensive guard for manual scan
                logger.exception("single_scan_error", symbol=symbol, timeframe=timeframe, error=str(exc))
                results.append({"symbol": symbol, "timeframe": timeframe, "status": "error", "error": str(exc)})
            finally:
                loop.close()
        return results

    def stop(self):
        self.is_running = False
        print("🛑 Ceo-Trade Durduruldu.")


def build_cli_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Ceo-Trade signal scanner")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="Symbols to scan, e.g. BTC/USDT ETH/USDT")
    parser.add_argument("--timeframes", nargs="*", default=DEFAULT_TIMEFRAMES, help="Timeframes to scan, e.g. 15m 1h")
    parser.add_argument("--initial-balance", type=float, default=5000.0, help="Initial paper account balance")
    parser.add_argument("--mode", choices=["paper", "backtest", "live"], default=None, help="Trading mode; defaults to the configured runtime mode")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between scans")
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle and exit")
    parser.add_argument("--status", action="store_true", help="Print the current dashboard summary and exit")
    parser.add_argument("--interactive", action="store_true", help="Launch the interactive terminal menu")
    parser.add_argument("--ui", action="store_true", help="Open the desktop dashboard window")
    return parser


def run_interactive_menu(orchestrator: CeoTradeOrchestrator):
    print("\n=== Ceo-Trade Interactive Menu ===")
    print("1) Status")
    print("2) One-shot scan")
    print("3) Start continuous loop")
    print("4) Stop continuous loop")
    print("5) Exit")

    while True:
        try:
            choice = input("\nSeciminiz (1-5): ").strip()
        except KeyboardInterrupt:
            print("\nÇıkış yapıldı.")
            return 0

        if choice == "1":
            print(orchestrator.get_dashboard_summary())
        elif choice == "2":
            results = orchestrator.run_once()
            print(f"Single scan completed: {len(results)} targets processed")
        elif choice == "3":
            orchestrator.start()
            asyncio.run(orchestrator.scan_loop())
        elif choice == "4":
            orchestrator.stop()
            print("Continuous loop stopped.")
        elif choice == "5":
            print("Menu closed.")
            return 0
        else:
            print("Geçersiz seçim.")


class DummyDashboardWindow:
    def __init__(self, orchestrator: CeoTradeOrchestrator | None = None):
        self.orchestrator = orchestrator or CeoTradeOrchestrator()
        self.summary_label = None
        self.positions_label = None
        self.signals_label = None
        self.mode_combo = None

    def set_mode(self, mode: str):
        mode = str(mode).lower()
        if mode not in {"paper", "live"}:
            return False
        self.orchestrator.mode_guard.set_mode(mode)
        return True

    def refresh(self):
        summary = self.orchestrator.get_dashboard_summary()
        self.summary_label = {
            "mode": summary["mode"],
            "status": summary["status"],
            "symbols": summary["symbols"],
            "timeframes": summary["timeframes"],
            "open_positions": summary["account"].get("open_positions", 0),
        }
        return self.summary_label

    def show(self):
        return None


class DashboardWindow:
    def __init__(self, orchestrator: CeoTradeOrchestrator | None = None):
        self.orchestrator = orchestrator or CeoTradeOrchestrator()

        try:
            from PyQt6.QtCore import QThread, QTimer, pyqtSignal
            from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget
        except Exception as exc:  # pragma: no cover - fallback for headless CI
            self._qt_error = exc
            self.widget = DummyDashboardWindow(self.orchestrator)
            self.summary_label = self.widget.summary_label
            self.mode_combo = self.widget.mode_combo
            return

        app = QApplication.instance() or QApplication([])
        self.app = app
        self.scan_worker = None

        self.widget = QWidget()
        self.widget.setWindowTitle("Ceo-Trade Dashboard")
        self.widget.resize(680, 460)
        layout = QVBoxLayout(self.widget)

        title = QLabel("Ceo-Trade Control Center")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        mode_row = QHBoxLayout()
        mode_label = QLabel("Mode:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["paper", "live"])
        self.mode_combo.setCurrentText(self.orchestrator.mode_guard.trading_mode)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.mode_combo)
        layout.addLayout(mode_row)

        notification_row = QHBoxLayout()
        notification_label = QLabel("Signal delivery:")
        self.notification_combo = QComboBox()
        self.notification_combo.addItems(["telegram", "whatsapp", "console"])
        self.notification_combo.setCurrentText(self.orchestrator.notification_channel)
        notification_row.addWidget(notification_label)
        notification_row.addWidget(self.notification_combo)
        layout.addLayout(notification_row)

        self.summary_label = QLabel("Status: loading...")
        self.summary_label.setWordWrap(True)
        self.positions_label = QLabel("Open positions: 0")
        self.signals_label = QLabel("Recent signals: none")
        self.notifications_label = QLabel("Notifications: ready")

        layout.addWidget(self.summary_label)
        layout.addWidget(self.positions_label)
        layout.addWidget(self.signals_label)
        layout.addWidget(self.notifications_label)

        buttons = QHBoxLayout()
        start_button = QPushButton("Start")
        stop_button = QPushButton("Stop")
        refresh_button = QPushButton("Refresh")
        test_signal_button = QPushButton("Send test signal")
        notification_settings_button = QPushButton("Notification settings")
        buttons.addWidget(start_button)
        buttons.addWidget(stop_button)
        buttons.addWidget(refresh_button)
        buttons.addWidget(test_signal_button)
        buttons.addWidget(notification_settings_button)
        layout.addLayout(buttons)

        def set_mode(mode: str):
            mode = str(mode).lower()
            if mode not in {"paper", "live"}:
                return False
            if not self.orchestrator.mode_guard.set_mode(mode):
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText(self.orchestrator.mode_guard.trading_mode)
                self.mode_combo.blockSignals(False)
                self.notifications_label.setText("Live mode is disabled; paper mode remains active")
                return False
            self.orchestrator.config.mode = mode
            self.refresh()
            return True

        def set_notification_channel(channel: str):
            self.orchestrator.notification_channel = str(channel).lower()
            self.orchestrator.config.notification_channel = self.orchestrator.notification_channel
            refresh_summary()

        def refresh_summary():
            summary = self.orchestrator.get_dashboard_summary()
            text = (
                f"Mode: {summary['mode']}\n"
                f"Status: {summary['status']}\n"
                f"Symbols: {', '.join(summary['symbols'])}\n"
                f"Timeframes: {', '.join(summary['timeframes'])}\n"
                f"Available balance: {summary['account'].get('available_balance_try', 0.0)}"
            )
            self.summary_label.setText(text)
            self.positions_label.setText(
                f"Open positions: {summary['account'].get('open_positions', 0)}"
            )
            recent = summary.get("recent_signals", [])
            if recent:
                signal_text = " | ".join([f"{row[2]}:{row[3]}" for row in recent[:3]])
                self.signals_label.setText(f"Recent signals: {signal_text}")
            else:
                self.signals_label.setText("Recent signals: none")
            self.notifications_label.setText(
                f"Notifications: {self.orchestrator.notification_channel} | {summary['status']}"
            )

        def start_action():
            if self.scan_worker is not None and self.scan_worker.isRunning():
                return
            self.orchestrator.start()

            class ScanWorker(QThread):
                scan_finished = pyqtSignal()

                def run(worker_self):
                    try:
                        asyncio.run(self.orchestrator.scan_loop())
                    except Exception as exc:
                        logger.exception("dashboard_scan_failed", error=str(exc))
                    finally:
                        worker_self.scan_finished.emit()

            self.scan_worker = ScanWorker(self.widget)
            self.scan_worker.scan_finished.connect(refresh_summary)
            self.scan_worker.start()
            refresh_summary()

        def stop_action():
            if self.orchestrator is not None:
                self.orchestrator.stop()
            refresh_summary()

        def send_test_signal():
            result = self.orchestrator.notifier.send_signal_alert(
                symbol="BTC/USDT",
                action="OPEN_LONG",
                entry_price=50000.0,
                stop_loss=49000.0,
                tp1=52000.0,
                channel=self.orchestrator.notification_channel,
            )
            status = result.get("status", "FAILED")
            detail = result.get("reason", "")
            refresh_summary()
            self.notifications_label.setText(
                f"{self.orchestrator.notification_channel}: {status} {detail}".strip()
            )

        def show_notification_settings():
            dialog = QDialog(self.widget)
            dialog.setWindowTitle("Notification settings")
            form = QFormLayout(dialog)
            token_input = QLineEdit()
            token_input.setEchoMode(QLineEdit.EchoMode.Password)
            token_input.setPlaceholderText(
                "Saved securely; leave blank to keep it"
                if self.orchestrator.notifier.telegram_token
                else "Telegram bot token"
            )
            chat_id_input = QLineEdit()
            chat_id_input.setText(self.orchestrator.notifier.telegram_chat_id or "")
            chat_id_input.setPlaceholderText("Telegram chat ID")
            webhook_input = QLineEdit()
            webhook_input.setEchoMode(QLineEdit.EchoMode.Password)
            webhook_input.setPlaceholderText(
                "Saved securely; leave blank to keep it"
                if self.orchestrator.notifier.whatsapp_webhook_url
                else "WhatsApp webhook URL"
            )
            form.addRow("Telegram bot token", token_input)
            form.addRow("Telegram chat ID", chat_id_input)
            form.addRow("WhatsApp webhook URL", webhook_input)
            save_button = QPushButton("Save securely")
            form.addRow(save_button)

            def save_notification_settings():
                token = token_input.text().strip()
                chat_id = chat_id_input.text().strip()
                webhook = webhook_input.text().strip()
                secrets = (
                    ("telegram_bot_token", token),
                    ("telegram_chat_id", chat_id),
                    ("whatsapp_webhook_url", webhook),
                )
                if any(value and not SecureStorage.save_secret(key, value) for key, value in secrets):
                    QMessageBox.warning(dialog, "Save failed", "Windows credential storage could not save the settings.")
                    return
                if token:
                    self.orchestrator.notifier.telegram_token = token
                    self.orchestrator.config.telegram_bot_token = token
                if chat_id:
                    self.orchestrator.notifier.telegram_chat_id = chat_id
                    self.orchestrator.config.telegram_chat_id = chat_id
                if webhook:
                    self.orchestrator.notifier.whatsapp_webhook_url = webhook
                    self.orchestrator.config.whatsapp_webhook_url = webhook
                dialog.accept()
                refresh_summary()
                if self.orchestrator.notifier.telegram_token and self.orchestrator.notifier.telegram_chat_id:
                    message = "Telegram settings are saved securely and ready for a test message."
                elif self.orchestrator.notifier.whatsapp_webhook_url:
                    message = "WhatsApp webhook is saved securely and ready for a test message."
                else:
                    message = "Settings saved securely. Telegram also needs a bot token and chat ID."
                QMessageBox.information(self.widget, "Settings saved", message)

            save_button.clicked.connect(save_notification_settings)
            dialog.exec()

        self.set_mode = set_mode
        self.mode_combo.currentTextChanged.connect(self.set_mode)
        self.notification_combo.currentTextChanged.connect(set_notification_channel)
        start_button.clicked.connect(start_action)
        stop_button.clicked.connect(stop_action)
        refresh_button.clicked.connect(refresh_summary)
        test_signal_button.clicked.connect(send_test_signal)
        notification_settings_button.clicked.connect(show_notification_settings)

        self.refresh = refresh_summary
        self.refresh_timer = QTimer(self.widget)
        self.refresh_timer.timeout.connect(refresh_summary)
        self.refresh_timer.start(1500)
        refresh_summary()

    def refresh(self):
        if hasattr(self, "widget") and hasattr(self.widget, "refresh"):
            return self.widget.refresh()
        if hasattr(self, "_qt_error"):
            return self.widget.refresh()
        return None

    def show(self):
        if hasattr(self, "widget"):
            self.widget.show()


def build_dashboard_window(orchestrator: CeoTradeOrchestrator | None = None):
    return DashboardWindow(orchestrator)


def launch_dashboard(orchestrator: CeoTradeOrchestrator):
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        print(orchestrator.get_dashboard_summary())
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = build_dashboard_window(orchestrator)
    if hasattr(window, "show"):
        window.show()
    return app.exec()


def main(argv=None):
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    config = load_app_config()

    selected_mode = args.mode or config.mode

    orchestrator = CeoTradeOrchestrator(
        symbols=args.symbols if args.symbols != DEFAULT_SYMBOLS else config.symbols,
        timeframes=args.timeframes if args.timeframes != DEFAULT_TIMEFRAMES else config.timeframes,
        initial_balance=args.initial_balance if args.initial_balance != 5000.0 else config.initial_balance,
        config=config,
    )
    orchestrator.scan_interval_seconds = args.interval if args.interval else orchestrator.scan_interval_seconds

    if selected_mode != "paper":
        if not orchestrator.mode_guard.set_mode(selected_mode):
            print("⚠️ Uygun olmayan mod; güvenli varsayılan olan paper modunda başlatılıyor.")
            orchestrator.mode_guard.set_mode("paper")
    else:
        orchestrator.mode_guard.set_mode("paper")

    if args.status:
        print(orchestrator.get_dashboard_summary())
        return 0

    if args.interactive:
        return run_interactive_menu(orchestrator)

    if args.once:
        results = orchestrator.run_once()
        print(f"Single scan completed: {len(results)} targets processed")
        return 0

    if args.ui or (argv is None and len(sys.argv) == 1):
        return launch_dashboard(orchestrator)

    print("\n=== Ceo-Trade Startup ===")
    print(f"Mode: {orchestrator.mode_guard.trading_mode}")
    print(f"Symbols: {', '.join(orchestrator.symbols)}")
    print(f"Timeframes: {', '.join(orchestrator.timeframes)}")
    print("========================\n")

    if args.interactive:
        return run_interactive_menu(orchestrator)

    try:
        asyncio.run(orchestrator.scan_loop())
    except KeyboardInterrupt:
        orchestrator.stop()
    return 0


if __name__ == "__main__":
    main()