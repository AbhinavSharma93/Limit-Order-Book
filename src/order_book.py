

from collections import deque
from src.order import Order, Side


class OrderBook:
    def __init__(self):
        
        self.bids: dict[float, deque[Order]] = {}
        self.asks: dict[float, deque[Order]] = {}

        
        self.order_locations: dict[int, tuple[Side, float]] = {}

    def _book_for(self, side: Side) -> dict[float, deque[Order]]:
        return self.bids if side is Side.BUY else self.asks

    def add_order(self, order: Order) -> None:
        book = self._book_for(order.side)
        if order.price not in book:
            book[order.price] = deque()
        book[order.price].append(order)
        self.order_locations[order.order_id] = (order.side, order.price)

    def cancel_order(self, order_id: int) -> Order | None:
        if order_id not in self.order_locations:
            return None

        side, price = self.order_locations[order_id]
        book = self._book_for(side)
        queue = book.get(price)
        if queue is None:
            return None

        cancelled = None
        for o in queue:
            if o.order_id == order_id:
                cancelled = o
                break

        if cancelled is not None:
            queue.remove(cancelled)
            if not queue:
                del book[price]
            del self.order_locations[order_id]

        return cancelled

    def best_bid(self) -> float | None:
        return max(self.bids.keys()) if self.bids else None

    def best_ask(self) -> float | None:
        return min(self.asks.keys()) if self.asks else None

    def depth(self, side: Side, n: int = 5) -> list[tuple[float, int]]:
        """Top n price levels for `side`, as (price, total_quantity), best price first."""
        book = self._book_for(side)
        prices = sorted(book.keys(), reverse=(side is Side.BUY))
        result = []
        for price in prices[:n]:
            total_qty = sum(o.quantity for o in book[price])
            result.append((price, total_qty))
        return result

    def __repr__(self) -> str:
        return f"OrderBook(best_bid={self.best_bid()}, best_ask={self.best_ask()})"