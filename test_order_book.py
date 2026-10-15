

from src.order import Order, Side, OrderType
from src.order_book import OrderBook


def make_order(order_id, side, price, qty, ts):
    return Order(order_id=order_id, side=side, order_type=OrderType.LIMIT,
                 price=price, quantity=qty, timestamp=ts)


def test_add_and_best_prices():
    book = OrderBook()
    book.add_order(make_order(1, Side.BUY, 100.0, 10, 0.001))
    book.add_order(make_order(2, Side.BUY, 100.5, 5, 0.002))   # better bid
    book.add_order(make_order(3, Side.SELL, 101.0, 8, 0.003))
    book.add_order(make_order(4, Side.SELL, 100.8, 3, 0.004))  # better ask

    assert book.best_bid() == 100.5
    assert book.best_ask() == 100.8
    print("add_and_best_prices: OK")


def test_fifo_order_at_same_price():
    book = OrderBook()
    book.add_order(make_order(1, Side.BUY, 100.0, 10, 0.001))
    book.add_order(make_order(2, Side.BUY, 100.0, 5, 0.002))

    queue = book.bids[100.0]
    assert queue[0].order_id == 1   # first in, first in queue
    assert queue[1].order_id == 2
    print("fifo_order_at_same_price: OK")


def test_cancel_removes_order_and_empty_level():
    book = OrderBook()
    book.add_order(make_order(1, Side.BUY, 100.0, 10, 0.001))

    cancelled = book.cancel_order(1)
    assert cancelled is not None
    assert cancelled.order_id == 1
    assert 100.0 not in book.bids          # price level cleaned up
    assert 1 not in book.order_locations
    assert book.best_bid() is None
    print("cancel_removes_order_and_empty_level: OK")


def test_cancel_unknown_id_returns_none():
    book = OrderBook()
    assert book.cancel_order(999) is None
    print("cancel_unknown_id_returns_none: OK")


def test_depth():
    book = OrderBook()
    book.add_order(make_order(1, Side.BUY, 100.0, 10, 0.001))
    book.add_order(make_order(2, Side.BUY, 100.0, 5, 0.002))
    book.add_order(make_order(3, Side.BUY, 99.5, 20, 0.003))

    d = book.depth(Side.BUY, n=2)
    assert d == [(100.0, 15), (99.5, 20)]  # best price first, quantities summed
    print("depth: OK")


if __name__ == "__main__":
    test_add_and_best_prices()
    test_fifo_order_at_same_price()
    test_cancel_removes_order_and_empty_level()
    test_cancel_unknown_id_returns_none()
    test_depth()
    print("All order_book tests passed.")