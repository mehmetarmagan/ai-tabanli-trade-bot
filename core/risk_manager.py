import math
from typing import Optional, Any


class RiskManager:
    def __init__(
        self,
        total_balance: float = 10000.0,
        risk_per_trade_pct: float = 0.02,
        max_risk_per_trade_pct: float = 0.05,
        atr_multiplier: float = 1.0,
        max_leverage: float = 5.0,
        estimated_cost_pct: float = 0.001,
    ):
        self.total_balance = float(total_balance)
        self.risk_per_trade_pct = float(risk_per_trade_pct)
        self.max_risk_per_trade_pct = float(max_risk_per_trade_pct)
        self.atr_multiplier = float(atr_multiplier)
        self.max_leverage = float(max_leverage)
        self.estimated_cost_pct = float(estimated_cost_pct)

    @staticmethod
    def _valid_positive(value: Any) -> bool:
        return isinstance(value, (int, float)) and math.isfinite(value) and value > 0

    def calculate_position_and_stop(
        self,
        entry_price: float,
        atr_value: float,
        direction: str = "BUY",
        risk_pct: Optional[float] = None,
        available_margin: Optional[float] = None,
        current_open_risk_pct: float = 0.0,
        allow_elevated_risk: bool = False,
        evidence_validated: bool = False,
    ) -> dict:
        if (
            not self._valid_positive(self.total_balance)
            or not self._valid_positive(entry_price)
            or not self._valid_positive(atr_value)
        ):
            return {"approved": False, "error": "Geçersiz giriş veya bakiye değerleri."}

        direction = direction.upper()
        is_long = direction in ("BUY", "LONG", "OPEN_LONG")

        selected_risk_pct = self.risk_per_trade_pct if risk_pct is None else float(risk_pct)
        if selected_risk_pct > self.max_risk_per_trade_pct:
            return {"approved": False, "error": "Risk oranı maksimum sınırı aşıyor."}

        stop_distance = self.atr_multiplier * atr_value
        if stop_distance >= entry_price:
            return {"approved": False, "error": "Stop mesafesi aşırı geniş."}

        stop_loss_price = (
            entry_price - stop_distance if is_long else entry_price + stop_distance
        )
        stop_distance_pct = stop_distance / entry_price

        if is_long:
            tp1 = entry_price + (stop_distance * 1.5)
            tp2 = entry_price + (stop_distance * 2.5)
            tp3 = entry_price + (stop_distance * 3.0)
        else:
            tp1 = entry_price - (stop_distance * 1.5)
            tp2 = entry_price - (stop_distance * 2.5)
            tp3 = entry_price - (stop_distance * 3.0)

        risk_amount_balance = self.total_balance * selected_risk_pct
        effective_loss_pct = stop_distance_pct + self.estimated_cost_pct
        position_notional_quote = (
            risk_amount_balance / effective_loss_pct if effective_loss_pct > 0 else 0
        )
        position_size_units = (
            position_notional_quote / entry_price if entry_price > 0 else 0
        )
        required_margin_quote = position_notional_quote / self.max_leverage

        return {
            "approved": True,
            "mode": "DYNAMIC_RISK_CALCULated",
            "direction": "LONG" if is_long else "SHORT",
            "entry_price": entry_price,
            "stop_loss_price": round(stop_loss_price, 4),
            "tp1": round(tp1, 4),
            "tp2": round(tp2, 4),
            "tp3": round(tp3, 4),
            "theoretical_rr": "1:3",
            "technical_rr": round(stop_distance * 3.0 / stop_distance, 2) if stop_distance > 0 else 0,
            "risk_amount_balance": round(risk_amount_balance, 2),
            "position_size_units": round(position_size_units, 4),
            "required_margin_quote": round(required_margin_quote, 2),
            "max_leverage": self.max_leverage,
        }