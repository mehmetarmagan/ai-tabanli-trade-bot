
import structlog
from typing import Any

from core.adapters.paper_adapter import PaperTradingAdapter
from core.adapters.security.mode_guard import TradingModeGuard
logger = structlog.get_logger()


class ExecutionEngine:
    """
    Strateji aksiyonlarını emir adaptörüne iletir.

    Bu sürüm yalnızca paper modunu destekler.
    Canlı işlem, pozisyon kapatma ve stop emri yönetimi
    tam olarak uygulanmadan etkinleştirilmez.
    """

    OPEN_ACTIONS = {
        "OPEN_LONG": "BUY",
        "OPEN_SHORT": "SELL",
    }

    def __init__(
        self,
        paper_adapter: PaperTradingAdapter | None = None,
        live_adapter: Any | None = None,
        mode_guard: TradingModeGuard | None = None,
    ):
        self.paper_adapter = paper_adapter
        self.live_adapter = live_adapter
        self.mode_guard = mode_guard or TradingModeGuard()
        self.kill_switch_active = False

    def execute_signal(
        self,
        signal_result: dict[str, Any],
        symbol: str,
        amount: float,
        price: float,
        stop_loss: float,
        leverage: float = 1.0,
    ) -> dict[str, Any]:
        if self.kill_switch_active:
            return {
                "status": "REJECTED",
                "reason": "Acil durdurma etkin.",
            }

        if not isinstance(signal_result, dict):
            return {
                "status": "REJECTED",
                "reason": "Sinyal sonucu geçersiz.",
            }

        action = signal_result.get(
            "action",
            signal_result.get("signal", "HOLD"),
        )

        if action == "HOLD":
            return {"status": "NO_ACTION", "reason": "İşlem sinyali yok."}

        if action in {"CLOSE_LONG", "CLOSE_SHORT"}:
            if self.mode_guard.trading_mode != "paper":
                return {
                    "status": "REJECTED",
                    "reason": "Pozisyon kapatma yalnızca paper modda çalışır.",
                }

            if not self.paper_adapter.connected:
                return {
                    "status": "REJECTED",
                    "reason": "Paper adaptörü bağlı değil.",
                }

            return self.paper_adapter.close_position(symbol=symbol, price=price, reason=f"{action}_EXECUTION")

        if action not in self.OPEN_ACTIONS:
            return {
                "status": "REJECTED",
                "reason": f"Bilinmeyen strateji aksiyonu: {action}",
            }

        side = self.OPEN_ACTIONS[action]

        if self.mode_guard.trading_mode == "live":
            if self.live_adapter is None:
                return {
                    "status": "REJECTED",
                    "reason": "Canlı adaptör bağlanmadı.",
                }

            if not getattr(self.live_adapter, "connected", False):
                connected = self.live_adapter.connect()
                if not connected:
                    return {
                        "status": "REJECTED",
                        "reason": "Canlı borsa bağlantısı kurulamadı.",
                    }

            if stop_loss is None:
                return {
                    "status": "REJECTED",
                    "reason": "Stop-loss belirlenmeden canlı pozisyon açılamaz.",
                }

            account_status = self.live_adapter.get_account_summary()
            risk_check = {"approved": True, "reason": "live_execution_allowed"}
            allowed, reason = self.mode_guard.validate_order_execution(
                account_status,
                risk_check,
                data_fresh=True,
                live_adapter_enabled=True,
                order_validated=True,
            )
            if not allowed:
                return {"status": "REJECTED", "reason": reason}

            result = self.live_adapter.create_order(
                symbol=symbol,
                side=side,
                amount=amount,
                price=price,
                stop_loss=stop_loss,
            )
            logger.info(
                "live_execution_result",
                action=action,
                symbol=symbol,
                status=result.get("status"),
            )
            return result

        if self.paper_adapter is None or not self.paper_adapter.connected:
            return {
                "status": "REJECTED",
                "reason": "Paper adaptörü bağlı değil.",
            }

        if stop_loss is None:
            return {
                "status": "REJECTED",
                "reason": "Stop-loss belirlenmeden pozisyon açılamaz.",
            }

        result = self.paper_adapter.execute_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            stop_loss=stop_loss,
            leverage=leverage,
        )

        logger.info(
            "execution_result",
            action=action,
            symbol=symbol,
            status=result.get("status"),
        )

        return result

    def emergency_stop(self) -> None:
        self.kill_switch_active = True
        logger.warning("execution_kill_switch_activated")

    def reset_emergency_stop(self) -> None:
        # Çağıran katman yeniden başlatma öncesinde kontrol yapmalıdır.
        self.kill_switch_active = False
        logger.warning("execution_kill_switch_reset")
