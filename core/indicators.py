
import numpy as np
import pandas as pd


class IndicatorEngine:
    """OHLCV verilerinden teknik göstergeler üretir."""

    RSI_PERIOD = 14
    ATR_PERIOD = 14
    SMA_PERIOD = 50
    EMA_PERIOD = 200

    @staticmethod
    def apply_all(df: pd.DataFrame) -> pd.DataFrame:
        if df is None:
            return df

        if not isinstance(df, pd.DataFrame):
            raise TypeError("Girdi bir pandas DataFrame olmalı.")

        if df.empty:
            return df.copy()

        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)

        if missing:
            raise ValueError(
                f"Eksik OHLCV kolonları: {sorted(missing)}"
            )

        result = df.copy()

        for column in required:
            result[column] = pd.to_numeric(
                result[column], errors="coerce"
            )

        # Sayısal olmayan ve sonsuz değerleri geçersiz say.
        result[list(required)] = result[list(required)].replace(
            [np.inf, -np.inf], np.nan
        )

        open_ = result["open"]
        high = result["high"]
        low = result["low"]
        close = result["close"]
        volume = result["volume"]

        # Veri tutarlılığı: hatalı satırları sessizce düzeltme.
        valid_prices = (
            (open_ > 0)
            & (high > 0)
            & (low > 0)
            & (close > 0)
            & (high >= low)
            & (high >= open_)
            & (high >= close)
            & (low <= open_)
            & (low <= close)
            & (volume >= 0)
        )

        invalid = (
            open_.isna()
            | high.isna()
            | low.isna()
            | close.isna()
            | volume.isna()
            | ~valid_prices
        )

        # Geçersiz satırların göstergelerini hesaplamaya katma.
        open_ = open_.where(~invalid)
        high = high.where(~invalid)
        low = low.where(~invalid)
        close = close.where(~invalid)
        volume = volume.where(~invalid)

        # SMA 50
        result["SMA_50"] = close.rolling(
            window=IndicatorEngine.SMA_PERIOD,
            min_periods=IndicatorEngine.SMA_PERIOD,
        ).mean()

        # EMA 200
        result["EMA_200"] = close.ewm(
            span=IndicatorEngine.EMA_PERIOD,
            adjust=False,
            min_periods=IndicatorEngine.EMA_PERIOD,
        ).mean()

        # RSI 14 — Wilder smoothing.
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        period = IndicatorEngine.RSI_PERIOD

        # Klasik Wilder başlangıcı: ilk 14 değişimin ortalaması.
        avg_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        rs = avg_gain.div(avg_loss.replace(0, np.nan))
        rsi = 100 - (100 / (1 + rs))

        rsi = rsi.mask(
            (avg_loss == 0) & (avg_gain > 0), 100.0
        )
        rsi = rsi.mask(
            (avg_gain == 0) & (avg_loss > 0), 0.0
        )
        rsi = rsi.mask(
            (avg_gain == 0) & (avg_loss == 0), 50.0
        )

        result["RSI_14"] = rsi

        # ATR 14 — True Range ve Wilder smoothing.
        previous_close = close.shift(1)

        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1, skipna=True)

        # İlk satırda önceki kapanış olmadığından H-L kullanılır.
        true_range = true_range.where(
            close.notna() & high.notna() & low.notna()
        )

        result["ATR_14"] = true_range.ewm(
            alpha=1 / IndicatorEngine.ATR_PERIOD,
            adjust=False,
            min_periods=IndicatorEngine.ATR_PERIOD,
        ).mean()

        # Günlük VWAP — yalnızca zaman indeksinde hesaplanır.
        typical_price = (high + low + close) / 3
        price_volume = typical_price * volume

        if isinstance(result.index, pd.DatetimeIndex):
            # Gün içi verinin kronolojik sıralı olması gerekir.
            if not result.index.is_monotonic_increasing:
                raise ValueError(
                    "VWAP için DatetimeIndex kronolojik sıralı olmalı."
                )

            # Saat dilimi varsa o saat diliminin gününe göre sıfırlanır.
            session = result.index.normalize()

            cumulative_pv = price_volume.groupby(
                session, sort=False
            ).cumsum()

            cumulative_volume = volume.groupby(
                session, sort=False
            ).cumsum()

            result["VWAP"] = cumulative_pv.div(
                cumulative_volume.where(cumulative_volume > 0)
            )
        else:
            # Zaman bilgisi yoksa günlük VWAP uydurulmaz.
            result["VWAP"] = np.nan

        return result
