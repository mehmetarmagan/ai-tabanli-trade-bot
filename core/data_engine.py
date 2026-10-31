
import pandas as pd
import ccxt
import structlog

logger = structlog.get_logger()


class MarketDataEngine:
    """CCXT üzerinden mum ve anlık piyasa verisi alan motor."""

    def __init__(self, exchange=None):
        self.exchange = exchange or ccxt.binance({
            "enableRateLimit": True,
            "timeout": 15000,
        })

    def fetch_current_price(self, symbol: str = "BTC/USDT") -> float | None:
        """Son işlem fiyatını Binance'ten çeker."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker.get("last")

            if price is None:
                logger.warning("ticker_price_missing", symbol=symbol)
                return None

            price = float(price)

            if not pd.notna(price) or price <= 0:
                logger.warning(
                    "ticker_price_invalid",
                    symbol=symbol,
                    price=price,
                )
                return None

            return price

        except Exception:
            logger.exception("ticker_fetch_error", symbol=symbol)
            return None

    def fetch_ohlcv(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 250,
        drop_unclosed_candle: bool = True,
    ) -> pd.DataFrame | None:

        if not isinstance(limit, int) or limit < 2:
            logger.error("invalid_ohlcv_limit", limit=limit)
            return None

        try:
            candles = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit,
            )

            if not candles:
                logger.warning(
                    "ohlcv_empty_response",
                    symbol=symbol,
                    timeframe=timeframe,
                )
                return None

            df = pd.DataFrame(
                candles,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )

            df["timestamp"] = pd.to_datetime(
                df["timestamp"],
                unit="ms",
                utc=True,
                errors="coerce",
            )

            numeric_columns = [
                "open", "high", "low", "close", "volume"
            ]

            for column in numeric_columns:
                df[column] = pd.to_numeric(
                    df[column],
                    errors="coerce",
                )

            df = df.dropna(
                subset=["timestamp", *numeric_columns]
            )

            df = (
                df.sort_values("timestamp")
                .drop_duplicates(
                    subset=["timestamp"],
                    keep="last",
                )
                .reset_index(drop=True)
            )

            if drop_unclosed_candle:
                timeframe_ms = (
                    self.exchange.parse_timeframe(timeframe) * 1000
                )

                now = pd.Timestamp.now(tz="UTC")

                candle_end = (
                    df["timestamp"]
                    + pd.to_timedelta(timeframe_ms, unit="ms")
                )

                df = df.loc[
                    candle_end <= now
                ].reset_index(drop=True)

            valid = (
                (df["open"] > 0)
                & (df["high"] > 0)
                & (df["low"] > 0)
                & (df["close"] > 0)
                & (df["volume"] >= 0)
                & (df["high"] >= df["low"])
                & (df["high"] >= df["open"])
                & (df["high"] >= df["close"])
                & (df["low"] <= df["open"])
                & (df["low"] <= df["close"])
            )

            df = df.loc[valid].reset_index(drop=True)

            if df.empty:
                logger.warning(
                    "ohlcv_no_valid_closed_candles",
                    symbol=symbol,
                    timeframe=timeframe,
                )
                return None

            df = df.set_index("timestamp", drop=True)
            df.index.name = "timestamp"

            logger.info(
                "ohlcv_fetched",
                symbol=symbol,
                timeframe=timeframe,
                rows=len(df),
                last_candle=str(df.index[-1]),
                last_close=float(df["close"].iloc[-1]),
            )

            return df

        except Exception:
            logger.exception(
                "fetch_ohlcv_error",
                symbol=symbol,
                timeframe=timeframe,
            )
            return None
