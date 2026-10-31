from typing import Any
import pandas as pd


class StrategyEngine:
    """
    EMA trend filtresi + RSI 14 + VWAP stratejisi (Geliştirilmiş & Esnetilmiş Sürüm).

    Üretilen aksiyonlar:
        OPEN_LONG
        CLOSE_LONG
        OPEN_SHORT
        CLOSE_SHORT
        HOLD
    """

    REQUIRED_COLUMNS = ("close", "EMA_200", "RSI_14", "VWAP")

    def __init__(
        self,
        rsi_oversold: float = 40.0,  # Esnetildi (Daha erken tepki için)
        rsi_overbought: float = 60.0, # Esnetildi
        enable_short: bool = True,   # SHORT yönü aktif hale getirildi!
        require_rsi_recovery: bool = False, # Katı kesişim şartı esnetildi
    ):
        if not 0 < rsi_oversold < rsi_overbought < 100:
            raise ValueError("RSI seviyeleri geçersiz.")

        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.enable_short = enable_short
        self.require_rsi_recovery = require_rsi_recovery

    @staticmethod
    def _is_valid_number(value: Any) -> bool:
        try:
            return pd.notna(value) and float("-inf") < float(value) < float("inf")
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _result(
        action: str,
        reason: str,
        strategy: str = "EMA_RSI_VWAP",
        **extra: Any,
    ) -> dict:
        return {
            "signal": action,
            "action": action,
            "strategy": strategy,
            "reason": reason,
            **extra,
        }

    def evaluate_strategies(
        self,
        df: pd.DataFrame,
        current_position: str = "FLAT",
    ) -> dict:
        current_position = current_position.upper()

        if current_position not in {"FLAT", "LONG", "SHORT"}:
            return self._result(
                "HOLD",
                "Geçersiz current_position değeri.",
            )

        if df is None or df.empty:
            return self._result("HOLD", "Veri bulunamadı.")

        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            return self._result(
                "HOLD",
                f"Eksik indikatör sütunları: {', '.join(missing)}",
            )

        if len(df) < 200:
            return self._result(
                "HOLD",
                "EMA 200 değerlendirmesi için en az 200 mum gerekli.",
            )

        last = df.iloc[-1]
        previous = df.iloc[-2]

        current_values = {
            "close": last["close"],
            "EMA_200": last["EMA_200"],
            "RSI_14": last["RSI_14"],
            "VWAP": last["VWAP"],
        }

        if not all(self._is_valid_number(v) for v in current_values.values()):
            return self._result(
                "HOLD",
                "Son mumda eksik veya geçersiz indikatör değeri var.",
            )

        close = float(last["close"])
        ema_200 = float(last["EMA_200"])
        rsi = float(last["RSI_14"])
        vwap = float(last["VWAP"])
        previous_rsi = float(previous["RSI_14"]) if self._is_valid_number(previous.get("RSI_14")) else rsi

        if close <= 0 or ema_200 <= 0 or vwap <= 0:
            return self._result(
                "HOLD",
                "Fiyat veya indikatör seviyesi geçersiz.",
            )

        # Trend rejimleri
        bullish_trend = close > ema_200
        bearish_trend = close < ema_200

        # LONG Pozisyon Yönetimi (Açık Pozisyon Varsa Çıkış Koşulları)
        if current_position == "LONG":
            if bearish_trend or rsi > 80:
                return self._result(
                    "CLOSE_LONG",
                    "Trend aşağı döndü veya RSI aşırı şişti; long kapatma sinyali.",
                    close=close,
                    ema_200=ema_200,
                    rsi=rsi,
                )
            return self._result("HOLD", "Long pozisyon korunuyor.", close=close, rsi=rsi)

        # SHORT Pozisyon Yönetimi (Açık Pozisyon Varsa Çıkış Koşulları)
        if current_position == "SHORT":
            if bullish_trend or rsi < 20:
                return self._result(
                    "CLOSE_SHORT",
                    "Trend yukarı döndü veya RSI dip yaptı; short kapatma sinyali.",
                    close=close,
                    ema_200=ema_200,
                    rsi=rsi,
                )
            return self._result("HOLD", "Short pozisyon korunuyor.", close=close, rsi=rsi)

        # --- YENİ GİRİŞ KOŞULLARI (FLAT) ---

        # 1. LONG Giriş Koşulu
        if bullish_trend and close >= vwap:
            if self.require_rsi_recovery:
                long_trigger = (previous_rsi < self.rsi_oversold) and (rsi >= self.rsi_oversold)
            else:
                long_trigger = rsi <= self.rsi_oversold  # Aşırı satım bölgesinde veya yakınında

            if long_trigger or (rsi > 40 and rsi < 60 and bullish_trend): # Esnetilmiş momentum filtresi
                return self._result(
                    "OPEN_LONG",
                    f"Boğa trendi aktif, fiyat VWAP üstünde. RSI: {rsi:.2f}",
                    close=close,
                    ema_200=ema_200,
                    vwap=vwap,
                    rsi=rsi,
                )

        # 2. SHORT Giriş Koşulu (Artık Aktif!)
        if self.enable_short and bearish_trend and close <= vwap:
            if self.require_rsi_recovery:
                short_trigger = (previous_rsi > self.rsi_overbought) and (rsi <= self.rsi_overbought)
            else:
                short_trigger = rsi >= self.rsi_overbought  # Aşırı alım bölgesinde

            if short_trigger or (rsi > 40 and rsi < 60 and bearish_trend):
                return self._result(
                    "OPEN_SHORT",
                    f"Ayı trendi aktif, fiyat VWAP altında. RSI: {rsi:.2f}",
                    close=close,
                    ema_200=ema_200,
                    vwap=vwap,
                    rsi=rsi,
                )

        return self._result(
            "HOLD",
            f"Filtreler bekleniyor. Trend: {'Yükseliş' if bullish_trend else 'Düşüş'}, RSI: {rsi:.2f}",
            close=close,
            ema_200=ema_200,
            vwap=vwap,
            rsi=rsi,
        )