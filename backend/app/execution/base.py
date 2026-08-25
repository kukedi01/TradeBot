from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float


class ExecutionEngine(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, size_fraction: float, reason: str) -> Fill:
        ...

    @abstractmethod
    def get_balance(self) -> dict:
        ...
