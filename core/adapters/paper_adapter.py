
import math
import structlog
from typing import Any

from core.adapters.exchange_adapter import BaseExchangeAdapter

logger = structlog.get_logger()


class PaperTradingAdapter(BaseExchangeAdapter):
    def __init__(self, initial_equity_try: float = 10000.0):
        if not math.isfinite(initial_equity_try) or initial_equity_try <= 0:
            raise ValueError("Başlangıç bakiyesi pozitif ve sonlu olmalı.")

        self.initial_equity_try = float(initial_equity_try)
        self.equity_try = float(initial_equity_try)
        self.available_equity_try = float(initial_equity_try)

        self.positions: dict[str, dict[str, Any]] = {}
        self.orders: list[dict[str, Any]] = []
        self.connected = False
        self._order_counter = 0

        logger.info(
            "paper_trading_adapter_initialized",
            initial_equity=initial_equity_try,
        )

    def connect(self) -> bool:
        self.connected = True
        return True

    def get_account_summary(self) -> dict[str, Any]:
        reserved = sum(
            position.get("reserved_margin_try", 0.0)
            for position in self.positions.values()
        )

        return {
            "mode": "PAPER",
            "total_balance_try": self.equity_try,
            "available_balance_try": self.available_equity_try,
            "reserved_margin_try": reserved,
            "open_positions": len(self.positions),
            "authenticated": True,
            "synced": True,
        }

    def get_position_summary(self, symbol: str) -> dict[str, Any]:
        if not symbol or not isinstance(symbol, str):
            return {"status": "FAILED", "reason": "Parite geçersiz."}

        position = self.positions.get(symbol)
        if position is None:
            return {"status": "NONE", "symbol": symbol, "reason": "Açık pozisyon yok."}

        return {
            "symbol": symbol,
            "status": "OPEN",
            "side": position.get("side"),
            "amount": float(position.get("amount", 0.0)),
            "entry_price": float(position.get("price", 0.0)),
            "stop_loss": position.get("stop_loss"),
            "leverage": float(position.get("leverage", 1.0)),
            "notional": float(position.get("notional", 0.0)),
            "reserved_margin_try": float(position.get("reserved_margin_try", 0.0)),
            "order_id": position.get("order_id"),
        }

    def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        return self.execute_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            stop_loss=stop_loss,
        )

    def execute_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float | None,
        stop_loss: float | None = None,
        leverage: float = 1.0,
    ) -> dict[str, Any]:
        if not self.connected:
            return {"status": "FAILED", "reason": "Paper adaptörü bağlı değil."}

        if not symbol or not isinstance(symbol, str):
            return {"status": "FAILED", "reason": "Parite geçersiz."}

        side = side.upper()
        if side not in {"BUY", "SELL"}:
            return {"status": "FAILED", "reason": "Yön BUY veya SELL olmalı."}

        values = [amount, price, leverage]
        if any(
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in values
        ):
            return {"status": "FAILED", "reason": "Miktar, fiyat veya kaldıraç geçersiz."}

        if stop_loss is not None:
            if not isinstance(stop_loss, (int, float)) or not math.isfinite(stop_loss):
                return {"status": "FAILED", "reason": "Stop-loss değeri geçersiz."}

            if side == "BUY" and not 0 < stop_loss < price:
                return {"status": "FAILED", "reason": "BUY stop-loss giriş fiyatının altında olmalı."}

            if side == "SELL" and not stop_loss > price:
                return {"status": "FAILED", "reason": "SELL stop-loss giriş fiyatının üstünde olmalı."}

        # Bu basit simülasyon, her paritede tek net pozisyon destekler.
        if symbol in self.positions:
            return {
                "status": "REJECTED",
                "reason": "Bu paritede açık pozisyon var; pozisyon ezilmedi.",
            }

        notional = float(amount) * float(price)
        margin = notional / float(leverage)

        if margin > self.available_equity_try:
            return {"status": "REJECTED", "reason": "Yeterli sanal teminat yok."}

        self._order_counter += 1
        order_id = f"PAPER_{self._order_counter}"

        record = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "amount": float(amount),
            "price": float(price),
            "stop_loss": stop_loss,
            "leverage": float(leverage),
            "notional": notional,
            "reserved_margin_try": margin,
            "status": "FILLED_SIMULATED",
            "mode": "PAPER",
        }

        self.available_equity_try -= margin
        self.positions[symbol] = record
        self.orders.append(record)

        logger.info("paper_order_simulated", order_id=order_id, symbol=symbol)

        return {"status": "SUCCESS", "order": record}

    def close_position(
        self,
        symbol: str,
        price: float | None = None,
        reason: str = "MANUAL_CLOSE",
    ) -> dict[str, Any]:
        if not self.connected:
            return {"status": "FAILED", "reason": "Paper adaptörü bağlı değil."}

        if not symbol or not isinstance(symbol, str):
            return {"status": "FAILED", "reason": "Parite geçersiz."}

        if symbol not in self.positions:
            return {"status": "FAILED", "reason": "Kapatılacak açık pozisyon yok."}

        position = self.positions.pop(symbol)
        close_price = float(price) if price is not None else float(position["price"])
        close_record = {
            "order_id": f"CLOSE_{position['order_id']}",
            "symbol": symbol,
            "side": "CLOSE",
            "amount": float(position["amount"]),
            "price": close_price,
            "stop_loss": None,
            "leverage": float(position["leverage"]),
            "status": "CLOSED_SIMULATED",
            "mode": "PAPER",
            "reason": reason,
            "closed_position": position,
        }
        self.orders.append(close_record)
        self.available_equity_try += float(position["reserved_margin_try"])

        logger.info("paper_position_closed", symbol=symbol, order_id=position["order_id"])
        return {"status": "SUCCESS", "order": close_record}

    def close(self) -> None:
        self.connected = False
