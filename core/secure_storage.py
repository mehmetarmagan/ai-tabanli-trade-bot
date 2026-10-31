
import keyring
import structlog
from typing import Optional

logger = structlog.get_logger()

SERVICE_NAME = "CEOTerminal_SecureStorage"


class SecureStorage:
    @staticmethod
    def save_secret(key_name: str, secret_value: str) -> bool:
        if not key_name or not isinstance(secret_value, str) or not secret_value:
            return False

        try:
            keyring.set_password(SERVICE_NAME, key_name, secret_value)

            # Kayıt sonrası geri okuyarak işlemi doğrula.
            saved_value = keyring.get_password(SERVICE_NAME, key_name)
            if saved_value != secret_value:
                logger.error("secret_save_verification_failed", key=key_name)
                return False

            logger.info("secret_saved", key=key_name)
            return True

        except Exception:
            logger.exception("secret_save_error", key=key_name)
            return False

    @staticmethod
    def get_secret(key_name: str) -> Optional[str]:
        if not key_name:
            return None

        try:
            return keyring.get_password(SERVICE_NAME, key_name)
        except Exception:
            logger.exception("secret_read_error", key=key_name)
            return None

    @staticmethod
    def delete_secret(key_name: str) -> bool:
        if not key_name:
            return False

        try:
            keyring.delete_password(SERVICE_NAME, key_name)
            logger.info("secret_deleted", key=key_name)
            return True
        except keyring.errors.PasswordDeleteError:
            return False
        except Exception:
            logger.exception("secret_delete_error", key=key_name)
            return False
