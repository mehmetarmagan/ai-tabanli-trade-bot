
from abc import ABC, abstractmethod
from typing import Any


class BaseExchangeAdapter(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def get_account_summary(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    def close(self) -> None:
        """Adaptörün kaynaklarını kapatır."""
        pass
