from __future__ import annotations

import json
from typing import Any

import requests


class NotificationService:
    """Güvenli bildirim katmanı.

    Console, Telegram ve WhatsApp benzeri HTTP tabanlı servisler için tek bir
    arayüz sunar. Telegram için gerçek bot API çağrısı, WhatsApp için webhook
    veya servis URL'i desteklenir.
    """

    def __init__(
        self,
        telegram_token: str | None = None,
        telegram_chat_id: str | None = None,
        whatsapp_number: str | None = None,
        whatsapp_webhook_url: str | None = None,
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.whatsapp_number = whatsapp_number
        self.whatsapp_webhook_url = whatsapp_webhook_url

    def _send_telegram(self, message: str) -> dict[str, Any]:
        if not self.telegram_token or not self.telegram_chat_id:
            return {
                "status": "NOT_CONFIGURED",
                "channel": "telegram",
                "message": message,
                "reason": "Telegram ayarları eksik.",
            }

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            response = requests.post(url, data=payload, timeout=15)
            body = response.json() if hasattr(response, "json") else {}
            if response.status_code in {200, 201} and body.get("ok") is True:
                return {
                    "status": "SUCCESS",
                    "channel": "telegram",
                    "message": message,
                    "provider": "telegram",
                }
            return {
                "status": "FAILED",
                "channel": "telegram",
                "message": message,
                "provider": "telegram",
                "reason": body.get("description", "Telegram API çağrısı başarısız."),
            }
        except Exception as exc:  # pragma: no cover - network layer failure path
            return {
                "status": "FAILED",
                "channel": "telegram",
                "message": message,
                "provider": "telegram",
                "reason": f"Telegram gönderimi başarısız: {exc}",
            }

    def _send_whatsapp(self, message: str) -> dict[str, Any]:
        if self.whatsapp_webhook_url:
            payload = {"text": message, "message": message}
            try:
                response = requests.post(self.whatsapp_webhook_url, data=payload, timeout=15)
                body = response.json() if hasattr(response, "json") else {}
                if response.status_code in {200, 201}:
                    return {
                        "status": "SUCCESS",
                        "channel": "whatsapp",
                        "message": message,
                        "provider": "whatsapp",
                    }
                return {
                    "status": "FAILED",
                    "channel": "whatsapp",
                    "message": message,
                    "provider": "whatsapp",
                    "reason": body.get("message", "WhatsApp webhook çağrısı başarısız."),
                }
            except Exception as exc:  # pragma: no cover - network layer failure path
                return {
                    "status": "FAILED",
                    "channel": "whatsapp",
                    "message": message,
                    "provider": "whatsapp",
                    "reason": f"WhatsApp gönderimi başarısız: {exc}",
                }

        if not self.whatsapp_number:
            return {
                "status": "NOT_CONFIGURED",
                "channel": "whatsapp",
                "message": message,
                "reason": "WhatsApp numarası veya webhook URL'i eksik.",
            }

        return {
            "status": "NOT_CONFIGURED",
            "channel": "whatsapp",
            "message": message,
            "reason": "WhatsApp numarası tek başına mesaj gönderemez; bir WhatsApp webhook sağlayıcısı yapılandırılmalıdır.",
        }

    def send_message(self, message: str, channel: str = "console") -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            return {"status": "FAILED", "channel": channel, "reason": "Mesaj boş."}

        channel_name = str(channel).lower()

        if channel_name == "console":
            print(f"[NOTIFY][{channel_name}] {message}")
            return {
                "status": "SUCCESS",
                "channel": channel_name,
                "message": message,
            }

        if channel_name == "telegram":
            return self._send_telegram(message)

        if channel_name == "whatsapp":
            return self._send_whatsapp(message)

        return {
            "status": "FAILED",
            "channel": channel_name,
            "message": message,
            "reason": "Desteklenmeyen kanal.",
        }

    def send_signal_alert(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        channel: str = "console",
    ) -> dict[str, Any]:
        payload = {
            "symbol": symbol,
            "action": action,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
        }
        message = (
            f"{symbol} | {action} | Entry: {entry_price} | "
            f"SL: {stop_loss} | TP1: {tp1}"
        )
        result = self.send_message(message, channel=channel)
        result["payload"] = payload
        return result
