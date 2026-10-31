from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "SUI/USDT",
]
DEFAULT_TIMEFRAMES = ["15m", "1h"]


def _read_dotenv(path: str | os.PathLike[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = Path(path)
    if not env_file.exists():
        return values

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _as_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        cleaned = [part for part in parts if part]
        return cleaned or list(default)
    return list(default)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None or str(value).strip() == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass
class AppConfig:
    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    timeframes: list[str] = field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))
    mode: str = "paper"
    initial_balance: float = 5000.0
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    whatsapp_number: str | None = None
    whatsapp_webhook_url: str | None = None
    notification_channel: str = "telegram"
    live_trading_enabled: bool = False
    scan_interval_seconds: int = 60

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = None) -> "AppConfig":
        file_values = _read_dotenv(env_file) if env_file else {}
        merged = {**file_values, **os.environ}

        symbols = _as_list(merged.get("CEO_TRADE_SYMBOLS") or merged.get("TRADING_SYMBOLS"), DEFAULT_SYMBOLS)
        timeframes = _as_list(merged.get("CEO_TRADE_TIMEFRAMES") or merged.get("TRADING_TIMEFRAMES"), DEFAULT_TIMEFRAMES)
        live_trading_enabled = _as_bool(merged.get("LIVE_TRADING_ENABLED"), False)
        mode = str(merged.get("CEO_TRADE_MODE") or merged.get("TRADING_MODE") or "paper").lower()
        if mode not in {"paper", "backtest", "live"}:
            mode = "paper"
        if mode == "live" and not live_trading_enabled:
            mode = "paper"
        notification_channel = str(merged.get("CEO_TRADE_NOTIFICATION_CHANNEL") or "telegram").lower()
        if notification_channel not in {"telegram", "whatsapp", "console"}:
            notification_channel = "telegram"

        return cls(
            symbols=symbols,
            timeframes=timeframes,
            mode=mode,
            initial_balance=_as_float(
                merged.get("CEO_TRADE_INITIAL_BALANCE") or merged.get("INITIAL_BALANCE") or 5000.0,
                5000.0,
            ),
            telegram_bot_token=(merged.get("TELEGRAM_BOT_TOKEN") or merged.get("TELEGRAM_TOKEN") or None),
            telegram_chat_id=(merged.get("TELEGRAM_CHAT_ID") or None),
            whatsapp_number=(merged.get("WHATSAPP_NUMBER") or None),
            whatsapp_webhook_url=(merged.get("WHATSAPP_WEBHOOK_URL") or None),
            notification_channel=notification_channel,
            live_trading_enabled=live_trading_enabled,
            scan_interval_seconds=int(
                merged.get("CEO_TRADE_SCAN_INTERVAL")
                or merged.get("SCAN_INTERVAL_SECONDS")
                or 60
            ),
        )


def load_app_config(env_file: str | os.PathLike[str] | None = None) -> AppConfig:
    default_env = Path(__file__).resolve().parents[1] / ".env"
    config_path = env_file or str(default_env)
    return AppConfig.from_env(config_path)
