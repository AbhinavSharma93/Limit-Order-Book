import csv
from dataclasses import dataclass
from src.order import Order, Side, OrderType
from src.matching_engine import MatchingEngine

PRICE_SCALE = 10000

MESSAGE_TYPE_NEW = 1
MESSAGE_TYPE_PARTIAL_CANCEL = 2
MESSAGE_TYPE_DELETE = 3
MESSAGE_TYPE_EXEC_VISIBLE = 4
MESSAGE_TYPE_EXEC_HIDDEN = 5
MESSAGE_TYPE_CROSS = 6
MESSAGE_TYPE_HALT = 7


@dataclass
class LobsterMessage:
    row_index: int
    time: float
    msg_type: int
    order_id: int
    size: int
    price: float   # already converted to dollars
    side: Side     # only meaningful for types that carry a real direction


def load_messages(filepath: str) -> list[LobsterMessage]:
    messages = []
    with open(filepath, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            time_ = float(row[0])
            msg_type = int(row[1])
            order_id = int(row[2])
            size = int(row[3])
            raw_price = int(row[4])
            direction = int(row[5])

            price = raw_price / PRICE_SCALE
            side = Side.BUY if direction == 1 else Side.SELL

            messages.append(LobsterMessage(
                row_index=i, time=time_, msg_type=msg_type,
                order_id=order_id, size=size, price=price, side=side,
            ))
    return messages


def load_orderbook(filepath: str, n_levels: int = 5) -> list[dict]:
    snapshots = []
    with open(filepath, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            snapshot = {"asks": [], "bids": []}
            for lvl in range(n_levels):
                base = lvl * 4
                ask_price = int(row[base]) / PRICE_SCALE
                ask_size = int(row[base + 1])
                bid_price = int(row[base + 2]) / PRICE_SCALE
                bid_size = int(row[base + 3])
                snapshot["asks"].append((ask_price, ask_size))
                snapshot["bids"].append((bid_price, bid_size))
            snapshots.append(snapshot)
    return snapshots


def _find_order_quantity(engine: MatchingEngine, order_id: int) -> int | None:
    """Look up an order's current resting quantity by scanning its price level."""
    loc = engine.book.order_locations.get(order_id)
    if loc is None:
        return None
    side, price = loc
    book = engine.book._book_for(side)
    for o in book.get(price, []):
        if o.order_id == order_id:
            return o.quantity
    return None


def replay_messages(engine: MatchingEngine, messages: list[LobsterMessage],
                     verbose: bool = False) -> dict:
    """
    Feeds messages through the engine. Returns a summary dict with counts of
    each message type processed and any warnings (e.g. cancel/delete for an
    order not found in the book — can happen for orders placed before the
    sample window started).
    """
    stats = {"new": 0, "partial_cancel": 0, "delete": 0,
              "exec_visible": 0, "exec_hidden": 0, "cross": 0, "halt": 0,
              "warnings": []}

    for msg in messages:
        if msg.msg_type == MESSAGE_TYPE_NEW:
            order = Order(
                order_id=msg.order_id, side=msg.side, order_type=OrderType.LIMIT,
                price=msg.price, quantity=msg.size, timestamp=msg.time,
            )
            engine.submit_order(order)
            stats["new"] += 1

        elif msg.msg_type == MESSAGE_TYPE_PARTIAL_CANCEL:
            current_qty = _find_order_quantity(engine, msg.order_id)
            if current_qty is None:
                stats["warnings"].append(
                    f"row {msg.row_index}: partial cancel for unknown order {msg.order_id}")
                continue
            new_qty = current_qty - msg.size
            if new_qty > 0:
                engine.modify_order(msg.order_id, new_quantity=new_qty)
            else:
                engine.cancel_order(msg.order_id)
            stats["partial_cancel"] += 1

        elif msg.msg_type == MESSAGE_TYPE_DELETE:
            result = engine.cancel_order(msg.order_id)
            if result is None:
                stats["warnings"].append(
                    f"row {msg.row_index}: delete for unknown order {msg.order_id}")
            stats["delete"] += 1

        elif msg.msg_type == MESSAGE_TYPE_EXEC_VISIBLE:
            
            current_qty = _find_order_quantity(engine, msg.order_id)
            if current_qty is None:
                stats["warnings"].append(
                    f"row {msg.row_index}: execution against unknown order {msg.order_id}")
            else:
                new_qty = current_qty - msg.size
                if new_qty > 0:
                    engine.modify_order(msg.order_id, new_quantity=new_qty)
                else:
                    engine.cancel_order(msg.order_id)
            stats["exec_visible"] += 1

        elif msg.msg_type == MESSAGE_TYPE_EXEC_HIDDEN:
            stats["exec_hidden"] += 1  

        elif msg.msg_type == MESSAGE_TYPE_CROSS:
            stats["cross"] += 1  

        elif msg.msg_type == MESSAGE_TYPE_HALT:
            stats["halt"] += 1  

        if verbose and msg.row_index % 5000 == 0:
            print(f"...processed row {msg.row_index}")

    return stats

def seed_book_from_snapshot(engine: MatchingEngine, snapshot: dict) -> None:
    """
    Seeds the engine's book with LOBSTER's row-0 orderbook snapshot, standing
    in for pre-market orders that never appear in the message file. Uses
    synthetic negative order IDs and an earliest possible timestamp so these
    always sit at the front of their price level's queue.
    """
    synthetic_id = -1
    for price, qty in snapshot["bids"]:
        if qty > 0:
            order = Order(order_id=synthetic_id, side=Side.BUY, order_type=OrderType.LIMIT,
                          price=price, quantity=qty, timestamp=-1.0)
            engine.book.add_order(order)
            synthetic_id -= 1
    for price, qty in snapshot["asks"]:
        if qty > 0:
            order = Order(order_id=synthetic_id, side=Side.SELL, order_type=OrderType.LIMIT,
                          price=price, quantity=qty, timestamp=-1.0)
            engine.book.add_order(order)
            synthetic_id -= 1