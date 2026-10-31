
import math
import structlog
from typing import Any

import ccxt

from core.adapters.exchange_adapter import BaseExchangeAdapter
from core.secure_storage import SecureStorage

logger = structlog.get_logger()


class BinanceFuturesAdapter(BaseExchangeAdapter):
    def __init__(
        self,
        is_testnet: bool = True,
        allow_live_orders: bool = False,
    ):
        self.is_testnet = is_testnet
        self.allow_live_orders = allow_live_orders
        self.exchange = None
        self.authenticated = False
        self.connected = False

        # Testnet dışında emir gönderimi ayrıca kapalı kalır.
        if not is_testnet and not allow_live_orders:
            logger.warning("live_order_execution_disabled")

    def connect(self) -> bool:
        api_key = SecureStorage.get_secret("binance_api_key")
        secret_key = SecureStorage.get_secret("binance_secret_key")

        if not api_key or not secret_key:
            logger.error("futures_adapter_credentials_missing")
            self.authenticated = False
            self.connected = False
            return False

        try:
            exchange = ccxt.binanceusdm({
                "apiKey": api_key,
                "secret": secret_key,
                "enableRateLimit": True,
                "timeout": 15000,
                "options": {"defaultType": "future"},
            })

            # Sandbox ayarı ilk API çağrısından önce yapılmalı.
            if self.is_testnet:
                exchange.set_sandbox_mode(True)

            exchange.load_markets()
            exchange.fetch_balance()

            self.exchange = exchange
            self.authenticated = True
            self.connected = True

            logger.info(
                "futures_adapter_connected",
                testnet=self.is_testnet,
            )
            return True

        except Exception:
            logger.exception("futures_connection_failed")
            self.exchange = None
            self.authenticated = False
            self.connected = False
            return False

    def get_account_summary(self) -> dict[str, Any]:
        if not self.connected or self.exchange is None:
            return {
                "mode": "TESTNET" if self.is_testnet else "LIVE",
                "authenticated": False,
                "synced": False,
                "error": "Borsa bağlantısı yok.",
            }

        try:
            balance = self.exchange.fetch_balance()
            positions = self.exchange.fetch_positions()

            return {
                "mode": "TESTNET" if self.is_testnet else "LIVE",
                "authenticated": self.authenticated,
                "synced": True,
                "balance": balance,
                "open_positions": positions,
            }

        except Exception:
            logger.exception("futures_account_sync_failed")
            return {
                "mode": "TESTNET" if self.is_testnet else "LIVE",
                "authenticated": self.authenticated,
                "synced": False,
                "error": "Hesap senkronizasyonu başarısız.",
            }

    def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        if not self.connected or not self.authenticated or self.exchange is None:
            return {"status": "FAILED", "reason": "Borsa bağlantısı doğrulanmadı."}

        if not self.is_testnet and not self.allow_live_orders:
            return {
                "status": "REJECTED",
                "reason": "Canlı emir gönderimi yapılandırmada kapalı.",
            }

        side = side.lower()

        if side not in {"buy", "sell"}:
            return {"status": "REJECTED", "reason": "Yön buy veya sell olmalı."}

        if (
            not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount <= 0
        ):
            return {"status": "REJECTED", "reason": "Miktar geçersiz."}

        if price is not None and (
            not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            return {"status": "REJECTED", "reason": "Limit fiyatı geçersiz."}

        if stop_loss is not None:
            return {
                "status": "REJECTED",
                "reason": (
                    "Stop-loss bu metotta borsaya bağlanmıyor. "
                    "Ayrı koruyucu emir akışı kurulmadan emir reddedildi."
                ),
            }

        try:
            # CCXT sembol formatı, örneğin BTC/USDT:USDT,
            # borsanın yüklenen market listesine göre doğrulanmalı.
            if symbol not in self.exchange.markets:
                return {
                    "status": "REJECTED",
                    "reason": f"Desteklenmeyen veya geçersiz sembol: {symbol}",
                }

            market = self.exchange.market(symbol)
            amount = float(self.exchange.amount_to_precision(symbol, amount))

            if amount <= 0:
                return {"status": "REJECTED", "reason": "Yuvarlanmış miktar sıfır."}

            limits = market.get("limits", {})
            min_amount = (limits.get("amount") or {}).get("min")

            if min_amount is not None and amount < min_amount:
                return {
                    "status": "REJECTED",
                    "reason": "Miktar borsanın minimum işlem miktarından düşük.",
                }

            order_type = "market" if price is None else "limit"
            if order_type == "limit":
                price = float(self.exchange.price_to_precision(symbol, price))

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params={},
            )

            logger.info(
                "futures_order_submitted",
                symbol=symbol,
                side=side,
                order_id=order.get("id"),
                testnet=self.is_testnet,
            )

            return {"status": "SUCCESS", "order": order}

        except Exception:
            logger.exception("futures_order_error")
            return {
                "status": "FAILED",
                "reason": "Borsa emri başarısız oldu; uygulama günlüğünü kontrol et.",
            }

    def close(self) -> None:
        self.exchange = None
        self.authenticated = False
        self.connected = False
