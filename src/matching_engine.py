

from dataclasses import dataclass
from src.order import Order, Side, OrderType
from src.order_book import OrderBook


@dataclass
class Trade:
    buy_order_id: int
    sell_order_id: int
    price: float
    quantity: int
    timestamp: float


class MatchingEngine:
    def __init__(self):
        self.book = OrderBook()
        self.trades: list[Trade] = []

    
    def submit_order(self, order: Order) -> list[Trade]:
        
        new_trades = []

        opposite_side = order.side.opposite()

        while not order.is_filled and self._crosses(order, opposite_side):
            level_trades = self._match_at_best_level(order, opposite_side)
            if not level_trades:
                break  # safety valve: nothing matched, avoid infinite loop
            new_trades.extend(level_trades)

        
        if not order.is_filled and order.order_type is OrderType.LIMIT:
            self.book.add_order(order)

        self.trades.extend(new_trades)
        return new_trades

    def cancel_order(self, order_id: int) -> Order | None:
        return self.book.cancel_order(order_id)

    def modify_order(self, order_id: int, new_price: float = None,
                      new_quantity: int = None, new_timestamp: float = None) -> Order | None:
        
        side, old_price = self.book.order_locations.get(order_id, (None, None))
        if side is None:
            return None  # unknown order

        if new_price is not None and new_price != old_price:
            old_order = self.book.cancel_order(order_id)
            if old_order is None:
                return None
            qty = new_quantity if new_quantity is not None else old_order.quantity
            replacement = Order(
                order_id=old_order.order_id,
                side=old_order.side,
                order_type=old_order.order_type,
                price=new_price,
                quantity=qty,
                timestamp=new_timestamp if new_timestamp is not None else old_order.timestamp,
            )
            
            self.submit_order(replacement)
            return replacement


        if new_quantity is not None:
            book = self.book._book_for(side)
            for o in book[old_price]:
                if o.order_id == order_id:
                    if new_quantity > o.quantity:
                        raise ValueError("Quantity increase requires a new timestamp "
                                          "(would need to lose priority) — not supported "
                                          "as an in-place modify.")
                    o.quantity = new_quantity
                    return o

        return None

    
    def _crosses(self, order: Order, opposite_side: Side) -> bool:
        if order.order_type is OrderType.MARKET:
            best = self.book.best_ask() if opposite_side is Side.SELL else self.book.best_bid()
            return best is not None

        best = self.book.best_ask() if opposite_side is Side.SELL else self.book.best_bid()
        if best is None:
            return False
        if order.side is Side.BUY:
            return order.price >= best
        else:
            return order.price <= best

    def _match_at_best_level(self, order: Order, opposite_side: Side) -> list[Trade]:
        best_price = (self.book.best_ask() if opposite_side is Side.SELL
                      else self.book.best_bid())
        if best_price is None:
            return []

        opposite_book = self.book._book_for(opposite_side)
        queue = opposite_book[best_price]
        trades = []

        while queue and not order.is_filled:
            resting = queue[0]  # oldest at this price level = front of FIFO
            fill_qty = min(order.quantity, resting.quantity)

            order.fill(fill_qty)
            resting.fill(fill_qty)

            buy_id = order.order_id if order.side is Side.BUY else resting.order_id
            sell_id = resting.order_id if order.side is Side.BUY else order.order_id

            trades.append(Trade(
                buy_order_id=buy_id,
                sell_order_id=sell_id,
                price=best_price,
                quantity=fill_qty,
                timestamp=order.timestamp,
            ))

            if resting.is_filled:
                queue.popleft()
                del self.book.order_locations[resting.order_id]

        if not queue:
            del opposite_book[best_price]

        return trades