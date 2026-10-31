from core.execution_engine import ExecutionEngine
from core.adapters.futures_adapter import BinanceFuturesAdapter
from core.risk_manager import RiskManager
from core.market import MarketDataEngine as SplitMarketEngine
from core.trading import ExecutionEngine as SplitExecutionEngine
from core.storage import SignalDatabase
from core.market_data import MarketDataEngine as LegacyMarketDataEngine
from core.paper_adapter import PaperTradingAdapter as LegacyPaperAdapter
from core.security.mode_guard import TradingModeGuard as LegacyModeGuard
from ui.main import CeoTradeOrchestrator


def test_risk_manager_is_available():
    rm = RiskManager(total_balance=10000.0)
    assert rm.total_balance == 10000.0


def test_execution_and_futures_modules_import():
    assert ExecutionEngine is not None
    assert BinanceFuturesAdapter is not None
    assert CeoTradeOrchestrator is not None
    assert SplitMarketEngine is not None
    assert SplitExecutionEngine is not None
    assert SignalDatabase is not None


def test_legacy_compatibility_modules_import():
    assert LegacyMarketDataEngine is not None
    assert LegacyPaperAdapter is not None
    assert LegacyModeGuard is not None


def test_orchestrator_supports_multi_coin_and_timeframes():
    orchestrator = CeoTradeOrchestrator(
        symbols=["BTC/USDT", "ETH/USDT"],
        timeframes=["15m", "1h"],
    )

    assert ("BTC/USDT", "15m") in orchestrator.scan_targets
    assert ("ETH/USDT", "1h") in orchestrator.scan_targets
    assert len(orchestrator.scan_targets) == 4


def test_signal_aggregator_confirms_cross_timeframe_setup():
    from core.signal_aggregator import SignalAggregator

    aggregator = SignalAggregator()
    aggregated = aggregator.aggregate(
        [
            {"action": "OPEN_LONG", "timeframe": "15m", "confidence": 0.78},
            {"action": "OPEN_LONG", "timeframe": "1h", "confidence": 0.82},
            {"action": "HOLD", "timeframe": "4h", "confidence": 0.1},
        ]
    )

    assert aggregated["action"] == "OPEN_LONG"
    assert aggregated["confidence"] >= 0.75
    assert aggregated["timeframes"] == ["15m", "1h"]


def test_paper_adapter_supports_open_and_close_position():
    from core.adapters.paper_adapter import PaperTradingAdapter

    adapter = PaperTradingAdapter(initial_equity_try=5000.0)
    adapter.connect()

    result = adapter.execute_order(
        symbol="BTC/USDT",
        side="BUY",
        amount=0.1,
        price=60000.0,
        stop_loss=58000.0,
        leverage=5.0,
    )

    assert result["status"] == "SUCCESS"
    close_result = adapter.close_position("BTC/USDT")
    assert close_result["status"] == "SUCCESS"
    assert "BTC/USDT" not in adapter.positions


def test_paper_adapter_exposes_position_summary():
    from core.adapters.paper_adapter import PaperTradingAdapter

    adapter = PaperTradingAdapter(initial_equity_try=5000.0)
    adapter.connect()
    adapter.execute_order(
        symbol="ETH/USDT",
        side="BUY",
        amount=0.5,
        price=2500.0,
        stop_loss=2400.0,
        leverage=3.0,
    )

    summary = adapter.get_position_summary("ETH/USDT")
    assert summary["symbol"] == "ETH/USDT"
    assert summary["status"] == "OPEN"
    assert summary["side"] == "BUY"


def test_notification_service_supports_text_alerts():
    from core.notifications import NotificationService

    notifier = NotificationService()
    result = notifier.send_message("BTC/USDT OPEN_LONG", channel="console")

    assert result["status"] == "SUCCESS"
    assert result["channel"] == "console"


def test_notification_service_uses_telegram_api_when_configured(monkeypatch):
    from core.notifications import NotificationService

    called = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_post(url, data=None, timeout=15):
        called["url"] = url
        called["data"] = data
        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)
    notifier = NotificationService(telegram_token="abc", telegram_chat_id="123")
    result = notifier.send_message("BTC/USDT OPEN_LONG", channel="telegram")

    assert result["status"] == "SUCCESS"
    assert result["provider"] == "telegram"
    assert called["data"]["text"] == "BTC/USDT OPEN_LONG"


def test_notification_service_supports_whatsapp_webhook(monkeypatch):
    from core.notifications import NotificationService

    called = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"status": "success"}

    def fake_post(url, data=None, timeout=15):
        called["url"] = url
        called["data"] = data
        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)
    notifier = NotificationService(whatsapp_webhook_url="https://example.com/whatsapp")
    result = notifier.send_message("ETH/USDT OPEN_SHORT", channel="whatsapp")

    assert result["status"] == "SUCCESS"
    assert result["provider"] == "whatsapp"
    assert called["data"]["text"] == "ETH/USDT OPEN_SHORT"


def test_signal_database_tracks_recent_and_status_updates():
    from core.database import SignalDatabase

    db = SignalDatabase(db_name=":memory:")
    db.save_signal(
        symbol="SOL/USDT",
        action="OPEN_LONG",
        entry_price=120.0,
        stop_loss=115.0,
        tp1=130.0,
        tp2=140.0,
        tp3=150.0,
    )

    recent = db.get_recent_signals(limit=10)
    assert len(recent) == 1
    assert recent[0][2] == "SOL/USDT"

    updated = db.update_signal_status(signal_id=recent[0][0], status="FILLED")
    assert updated is True
    assert db.get_signal_by_id(recent[0][0])["status"] == "FILLED"


def test_orchestrator_dashboard_summary_exposes_safe_default_status():
    orchestrator = CeoTradeOrchestrator(symbols=["BTC/USDT"], timeframes=["15m"])
    summary = orchestrator.get_dashboard_summary()

    assert summary["mode"] == "paper"
    assert summary["symbols"] == ["BTC/USDT"]
    assert summary["timeframes"] == ["15m"]
    assert "account" in summary


def test_orchestrator_supports_safe_start_and_stop_cycle():
    orchestrator = CeoTradeOrchestrator(symbols=["BTC/USDT"], timeframes=["15m"])

    assert orchestrator.start() is True
    assert orchestrator.is_running is True

    orchestrator.stop()
    assert orchestrator.is_running is False


def test_app_config_reads_env_and_file_values(tmp_path, monkeypatch):
    from core.config import load_app_config

    env_path = tmp_path / ".env"
    env_path.write_text(
        "CEO_TRADE_SYMBOLS=BTC/USDT,ETH/USDT\n"
        "CEO_TRADE_TIMEFRAMES=15m,1h\n"
        "CEO_TRADE_MODE=paper\n"
        "TELEGRAM_BOT_TOKEN=abc123\n"
        "TELEGRAM_CHAT_ID=456\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("CEO_TRADE_SYMBOLS", "SOL/USDT")
    config = load_app_config(env_file=str(env_path))

    assert config.symbols == ["SOL/USDT"]
    assert config.timeframes == ["15m", "1h"]
    assert config.mode == "paper"
    assert config.telegram_bot_token == "abc123"
    assert config.telegram_chat_id == "456"


def test_orchestrator_supports_one_shot_scan():
    orchestrator = CeoTradeOrchestrator(symbols=["BTC/USDT"], timeframes=["15m"])

    results = orchestrator.run_once()

    assert isinstance(results, list)
    assert orchestrator.is_running is False


def test_cli_supports_single_run_and_status_flags():
    from ui.main import build_cli_parser

    args = build_cli_parser().parse_args(["--once", "--status"])

    assert args.once is True
    assert args.status is True


def test_cli_supports_interactive_menu_flag():
    from ui.main import build_cli_parser

    args = build_cli_parser().parse_args(["--interactive"])

    assert args.interactive is True


def test_live_mode_can_be_enabled_when_explicitly_configured():
    from core.adapters.security.mode_guard import TradingModeGuard

    guard = TradingModeGuard({"LIVE_TRADING_ENABLED": True, "TRADING_MODE": "live"})
    guard.set_user_confirmation(True)

    assert guard.trading_mode == "live"
    assert guard.set_mode("live") is True


def test_dashboard_window_can_be_built():
    from ui.main import build_dashboard_window

    widget = build_dashboard_window()

    assert widget is not None
    assert hasattr(widget, "show")
    assert hasattr(widget, "refresh")
    assert hasattr(widget, "summary_label")


def test_dashboard_window_has_mode_selector_for_live_and_paper():
    from ui.main import build_dashboard_window

    widget = build_dashboard_window()

    assert hasattr(widget, "mode_combo")
    assert hasattr(widget, "set_mode")
    assert widget.mode_combo is not None
