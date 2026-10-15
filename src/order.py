

from dataclasses import dataclass, field
from enum import Enum
import itertools


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"



_sequence_counter = itertools.count()


@dataclass
class Order:
    order_id: int
    side: Side
    order_type: OrderType
    price: float          # required for LIMIT, ignored for MARKET
    quantity: int          # remaining quantity — mutates on fills
    timestamp: float       # arrival time; THIS is the priority mechanism
    original_quantity: int = field(default=None)
    seq: int = field(default_factory=lambda: next(_sequence_counter))

    def __post_init__(self):
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError(f"LIMIT order {self.order_id} requires a price")
        if self.quantity <= 0:
            raise ValueError(f"Order {self.order_id} must have positive quantity")
        if self.original_quantity is None:
            self.original_quantity = self.quantity

    @property
    def is_filled(self) -> bool:
        return self.quantity == 0

    @property
    def filled_quantity(self) -> int:
        return self.original_quantity - self.quantity

    def fill(self, qty: int) -> None:
        if qty > self.quantity:
            raise ValueError(
                f"Cannot fill {qty} on order {self.order_id}; "
                f"only {self.quantity} remaining"
            )
        self.quantity -= qty

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, {self.side.value} {self.quantity}"
            f"{'' if self.quantity == self.original_quantity else f'/{self.original_quantity}'} "
            f"@ {self.price if self.order_type is OrderType.LIMIT else 'MKT'}, "
            f"t={self.timestamp})"
        )