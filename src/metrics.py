

from dataclasses import dataclass
from src.order import Order, Side, OrderType
from src.order_book import OrderBook
from src.matching_engine import MatchingEngine

EPSILON = 0.001



def queue_position(book: OrderBook, order_id: int) -> dict | None:
    
    loc = book.order_locations.get(order_id)
    if loc is None:
        return None
    side, price = loc

    level = book._book_for(side).get(price)
    if level is None:
        return None

    shares_ahead = 0
    orders_ahead = 0
    rank = None
    our_qty = 0

    for idx, o in enumerate(level):
        if o.order_id == order_id:
            rank = idx
            our_qty = o.quantity
            break
        shares_ahead += o.quantity
        orders_ahead += 1

    if rank is None:
        return None

    level_total = sum(o.quantity for o in level)
    shares_behind = level_total - shares_ahead - our_qty

    return {
        "order_id": order_id,
        "side": side,
        "price": price,
        "rank": rank,
        "shares_ahead": shares_ahead,
        "orders_ahead": orders_ahead,
        "our_quantity": our_qty,
        "shares_behind": shares_behind,
        "level_total": level_total,
    }


def queue_ahead_at_price(book: OrderBook, side: Side, price: float) -> int:
    
    level = book._book_for(side).get(price)
    if level is None:
        return 0
    return sum(o.quantity for o in level)



@dataclass
class FillOutcome:
    order_id: int
    shares_ahead_at_entry: int
    level_total_at_entry: int
    filled: bool
    fully_filled: bool
    messages_to_outcome: int


class FillTracker:
   

    def __init__(self, engine: MatchingEngine):
        self.engine = engine
        self.tracked: dict[int, dict] = {}
        self.outcomes: list[FillOutcome] = []
        self.clock = 0

    def tick(self):
        self.clock += 1

    def on_submit(self, order: Order):
        """Call immediately AFTER submitting a passive order."""
        pos = queue_position(self.engine.book, order.order_id)
        if pos is None:
            return  # order crossed immediately, never rested
        self.tracked[order.order_id] = {
            "shares_ahead": pos["shares_ahead"],
            "level_total": pos["level_total"],
            "original_qty": order.quantity,
            "entered_at": self.clock,
        }

    def on_execution(self, order_id: int, qty: int, remaining: int):
        """Call when a tracked order is (partially) executed."""
        info = self.tracked.get(order_id)
        if info is None:
            return
        if remaining <= 0:
            self.outcomes.append(FillOutcome(
                order_id=order_id,
                shares_ahead_at_entry=info["shares_ahead"],
                level_total_at_entry=info["level_total"],
                filled=True, fully_filled=True,
                messages_to_outcome=self.clock - info["entered_at"],
            ))
            del self.tracked[order_id]
        else:
            info["partially_filled"] = True

    def on_cancel(self, order_id: int):
        """Call when a tracked order is cancelled or deleted."""
        info = self.tracked.pop(order_id, None)
        if info is None:
            return
        self.outcomes.append(FillOutcome(
            order_id=order_id,
            shares_ahead_at_entry=info["shares_ahead"],
            level_total_at_entry=info["level_total"],
            filled=info.get("partially_filled", False),
            fully_filled=False,
            messages_to_outcome=self.clock - info["entered_at"],
        ))

    def fill_rate_by_queue_bucket(self, buckets=(0, 1, 100, 500, 1000, 5000)) -> list[dict]:
        
        rows = []
        edges = list(buckets) + [float("inf")]
        for lo, hi in zip(edges, edges[1:]):
            group = [o for o in self.outcomes if lo <= o.shares_ahead_at_entry < hi]
            if not group:
                continue
            n = len(group)
            any_fill = sum(1 for o in group if o.filled)
            full_fill = sum(1 for o in group if o.fully_filled)
            rows.append({
                "shares_ahead": f"{lo}" if hi == float('inf') else f"{lo}-{int(hi) - 1}",
                "n_orders": n,
                "any_fill_pct": 100 * any_fill / n,
                "full_fill_pct": 100 * full_fill / n,
                "median_msgs_to_outcome": sorted(o.messages_to_outcome for o in group)[n // 2],
            })
        return rows



def modify_cost_analysis(book: OrderBook, order_id: int,
                          new_price: float) -> dict | None:
    
    current = queue_position(book, order_id)
    if current is None:
        return None

    side = current["side"]
    shares_ahead_now = current["shares_ahead"]
    shares_ahead_after = queue_ahead_at_price(book, side, new_price)

    improves = shares_ahead_after < shares_ahead_now

    return {
        "order_id": order_id,
        "side": side,
        "current_price": current["price"],
        "new_price": new_price,
        "shares_ahead_now": shares_ahead_now,
        "orders_ahead_now": current["orders_ahead"],
        "shares_ahead_after_reprice": shares_ahead_after,
        "priority_lost": shares_ahead_now,   # your entire accrued position
        "net_change_in_shares_ahead": shares_ahead_after - shares_ahead_now,
        "improves_position": improves,
        "verdict": (
            f"Repricing reduces shares ahead by {shares_ahead_now - shares_ahead_after}"
            if improves else
            f"Repricing INCREASES shares ahead by {shares_ahead_after - shares_ahead_now} "
            f"- you surrender {shares_ahead_now} shares of accrued priority for a worse queue"
        ),
    }


def quantity_modify_is_free(book: OrderBook, order_id: int,
                             new_quantity: int) -> dict | None:
    
    before = queue_position(book, order_id)
    if before is None:
        return None
    if new_quantity > before["our_quantity"]:
        return {
            "order_id": order_id,
            "allowed": False,
            "reason": ("Increasing quantity in place would jump ahead of orders "
                        "that queued behind you. Real venues require a new order "
                        "for the increase, which means new timestamp and back of queue."),
        }
    return {
        "order_id": order_id,
        "allowed": True,
        "rank_before": before["rank"],
        "rank_after": before["rank"],          
        "shares_ahead_before": before["shares_ahead"],
        "shares_ahead_after": before["shares_ahead"],
        "priority_cost": 0,
        "note": "Quantity reduction preserves time priority; price change does not.",
    }

def _demo():
    """Worked example showing all three metrics on a constructed book."""
    engine = MatchingEngine()

    def add(oid, side, price, qty, ts):
        engine.submit_order(Order(order_id=oid, side=side,
                                   order_type=OrderType.LIMIT,
                                   price=price, quantity=qty, timestamp=ts))

    # Build a bid side with realistic depth
    add(1, Side.BUY, 100.00, 500, 0.001)
    add(2, Side.BUY, 100.00, 300, 0.002)
    add(3, Side.BUY, 100.00, 200, 0.003)   # our order - 800 shares ahead
    add(4, Side.BUY, 100.00, 400, 0.004)
    add(5, Side.BUY,  99.99,  50, 0.005)   # much thinner level below

    print("=" * 66)
    print("1. QUEUE POSITION")
    print("=" * 66)
    for oid in (1, 3, 4):
        p = queue_position(engine.book, oid)
        print(f"  Order {oid}: {p['our_quantity']} shares @ {p['price']}")
        print(f"    rank {p['rank']} | {p['shares_ahead']} shares ahead "
              f"({p['orders_ahead']} orders) | {p['shares_behind']} behind")
    print("\n  Orders 1 and 4 are at the SAME price with similar size, but")
    print("  order 1 trades after 0 shares are consumed and order 4 after 1000.")
    print("  Price alone tells you nothing about fill prospects.")

    print("\n" + "=" * 66)
    print("2. MODIFY COST - repricing to a thinner level")
    print("=" * 66)
    r = modify_cost_analysis(engine.book, 3, 99.99)
    print(f"  Order 3 currently: {r['shares_ahead_now']} shares ahead @ {r['current_price']}")
    print(f"  If repriced to {r['new_price']}: {r['shares_ahead_after_reprice']} shares ahead")
    print(f"  Net change: {r['net_change_in_shares_ahead']:+d} shares")
    print(f"  -> {r['verdict']}")
    print("\n  Here repricing DOWN in price improves queue position, because the")
    print("  lower level is far thinner. That is a real trade-off a passive")
    print("  trader faces: a worse price you actually get filled at may beat a")
    print("  better price you never reach.")

    print("\n" + "=" * 66)
    print("3. MODIFY COST - the quantity/price asymmetry")
    print("=" * 66)
    q = quantity_modify_is_free(engine.book, 3, 100)
    print(f"  Reducing order 3 from 200 to 100 shares:")
    print(f"    rank {q['rank_before']} -> {q['rank_after']}, "
          f"priority cost: {q['priority_cost']}")
    print(f"    {q['note']}")

    engine.modify_order(3, new_price=99.98, new_timestamp=0.010)
    after = queue_position(engine.book, 3)
    print(f"\n  Changing order 3's PRICE to 99.98:")
    print(f"    now rank {after['rank']} at a new level, "
          f"{after['shares_ahead']} shares ahead")
    print(f"    the original queue position at 100.00 is gone permanently")

    print("\n" + "=" * 66)
    print("WHY THIS MATTERS")
    print("=" * 66)
    print("  A passive trader's edge lives in queue position. Being early at a")
    print("  price is an asset that accrues silently and is destroyed instantly")
    print("  by a reprice. The asymmetry - free to shrink, costly to move -")
    print("  shapes real resting-order behaviour: traders shrink rather than")
    print("  move, and only reprice when the destination level is thin enough")
    print("  to justify surrendering everything they have accrued.")


if __name__ == "__main__":
    _demo()