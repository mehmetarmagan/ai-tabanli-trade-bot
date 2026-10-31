
import structlog
from typing import Any

logger = structlog.get_logger()


class TradingModeGuard:
    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}

        # Güvenli varsayılanlar.
        self.config = dict(config)
        self.live_trading_enabled = (
            config.get("LIVE_TRADING_ENABLED", False) is True
        )
        self.trading_mode = str(
            config.get("TRADING_MODE", "paper")
        ).lower()
        self.user_explicit_confirmed = False

        if self.trading_mode not in {"paper", "backtest", "live"}:
            self.trading_mode = "paper"

        if self.trading_mode == "live" and not self.live_trading_enabled:
            self.trading_mode = "paper"

        # Canlı mod, yalnızca LIVE_TRADING_ENABLED ve açık kullanım onayı ile etkin olur.
        if self.trading_mode == "live" and self.live_trading_enabled:
            self.user_explicit_confirmed = True

    def set_user_confirmation(self, confirmed: bool) -> None:
        self.user_explicit_confirmed = confirmed is True
        logger.warning(
            "trading_guard_user_confirmation_changed",
            confirmed=self.user_explicit_confirmed,
        )

    def set_mode(self, mode: str) -> bool:
        mode = str(mode).lower()

        if mode not in {"paper", "backtest", "live"}:
            return False

        # Canlı mod için diğer kontroller ayrıca zorunlu.
        if mode == "live" and not self.live_trading_enabled:
            logger.warning("live_mode_rejected_disabled")
            self.trading_mode = "paper"
            self.set_user_confirmation(False)
            return False

        self.trading_mode = mode

        if mode != "live":
            self.set_user_confirmation(False)

        return True

    def validate_order_execution(
        self,
        account_status: dict[str, Any],
        risk_check: dict[str, Any],
        data_fresh: bool,
        *,
        live_adapter_enabled: bool = False,
        kill_switch_active: bool = False,
        order_validated: bool = False,
    ) -> tuple[bool, str]:
        if kill_switch_active:
            return False, "Acil durdurma etkin."

        if self.trading_mode != "live":
            return False, "Canlı mod etkin değil."

        if not self.live_trading_enabled:
            return False, "LIVE_TRADING_ENABLED etkin değil."

        if not self.user_explicit_confirmed:
            return False, "Kullanıcının açık canlı işlem onayı bulunmuyor."

        if not live_adapter_enabled:
            return False, "Canlı emir adaptörü ayrıca etkinleştirilmemiş."

        if not account_status.get("authenticated", False):
            return False, "Borsa kimlik doğrulaması başarısız."

        if not account_status.get("synced", False):
            return False, "Hesap ve pozisyon senkronizasyonu tamamlanmadı."

        if not risk_check.get("approved", False):
            reason = risk_check.get(
                "reason",
                risk_check.get("error", "Bilinmeyen risk kontrolü hatası"),
            )
            return False, f"Risk kontrolü reddetti: {reason}"

        if not data_fresh:
            return False, "Piyasa verisi güncel değil."

        if not order_validated:
            return False, "Emir parametreleri henüz doğrulanmadı."

        return True, "Kontroller geçti; son emir öncesi kontroller yine zorunlu."
