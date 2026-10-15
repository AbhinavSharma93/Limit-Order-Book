

from src.order import Order, Side, OrderType
from src.matching_engine import MatchingEngine


def make_order(order_id, side, order_type, price, qty, ts):
    return Order(order_id=order_id, side=side, order_type=order_type,
                 price=price, quantity=qty, timestamp=ts)


def test_simple_full_match():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 10, 0.001))
    trades = engine.submit_order(make_order(2, Side.BUY, OrderType.LIMIT, 100.0, 10, 0.002))

    assert len(trades) == 1
    assert trades[0].price == 100.0
    assert trades[0].quantity == 10
    assert engine.book.best_bid() is None
    assert engine.book.best_ask() is None
    print("simple_full_match: OK")


def test_partial_match_rests_remainder():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.001))
    trades = engine.submit_order(make_order(2, Side.BUY, OrderType.LIMIT, 100.0, 10, 0.002))

    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert engine.book.best_ask() is None          # sell order fully consumed
    assert engine.book.best_bid() == 100.0          # remaining 5 rests
    assert engine.book.bids[100.0][0].quantity == 5
    print("partial_match_rests_remainder: OK")


def test_walks_multiple_price_levels():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.001))
    engine.submit_order(make_order(2, Side.SELL, OrderType.LIMIT, 100.5, 5, 0.002))
    trades = engine.submit_order(make_order(3, Side.BUY, OrderType.LIMIT, 100.5, 10, 0.003))

    assert len(trades) == 2
    assert trades[0].price == 100.0   # best price matched first
    assert trades[1].price == 100.5
    assert engine.book.best_ask() is None
    print("walks_multiple_price_levels: OK")


def test_non_crossing_limit_just_rests():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 101.0, 5, 0.001))
    trades = engine.submit_order(make_order(2, Side.BUY, OrderType.LIMIT, 100.0, 5, 0.002))

    assert len(trades) == 0
    assert engine.book.best_bid() == 100.0
    assert engine.book.best_ask() == 101.0
    print("non_crossing_limit_just_rests: OK")


def test_fifo_priority_respected():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.001))
    engine.submit_order(make_order(2, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.002))
    trades = engine.submit_order(make_order(3, Side.BUY, OrderType.LIMIT, 100.0, 5, 0.003))

    assert len(trades) == 1
    assert trades[0].sell_order_id == 1   # order 1 was first, fills first
    assert engine.book.asks[100.0][0].order_id == 2  # order 2 still resting
    print("fifo_priority_respected: OK")


def test_modify_price_loses_priority():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.001))
    engine.submit_order(make_order(2, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.002))

    # Order 1 modifies its price down slightly then back — simulate a
    # price-changing modify by moving it to a new price level.
    engine.modify_order(1, new_price=100.5, new_timestamp=0.010)

    assert 100.0 not in engine.book.asks or engine.book.asks[100.0][0].order_id == 2
    assert engine.book.asks[100.5][0].order_id == 1
    print("modify_price_loses_priority: OK")


def test_modify_quantity_keeps_priority():
    engine = MatchingEngine()
    engine.submit_order(make_order(1, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.001))
    engine.submit_order(make_order(2, Side.SELL, OrderType.LIMIT, 100.0, 5, 0.002))

    engine.modify_order(1, new_quantity=2)

    assert engine.book.asks[100.0][0].order_id == 1   # still first in queue
    assert engine.book.asks[100.0][0].quantity == 2
    print("modify_quantity_keeps_priority: OK")


if __name__ == "__main__":
    test_simple_full_match()
    test_partial_match_rests_remainder()
    test_walks_multiple_price_levels()
    test_non_crossing_limit_just_rests()
    test_fifo_priority_respected()
    test_modify_price_loses_priority()
    test_modify_quantity_keeps_priority()
    print("All matching_engine tests passed.")
    