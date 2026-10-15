

from collections import Counter
from src.order import Order, Side, OrderType
from src.matching_engine import MatchingEngine
from src.lobster_parser import (
    load_messages, load_orderbook,
    MESSAGE_TYPE_NEW, MESSAGE_TYPE_PARTIAL_CANCEL, MESSAGE_TYPE_DELETE,
    MESSAGE_TYPE_EXEC_VISIBLE, MESSAGE_TYPE_EXEC_HIDDEN,
    MESSAGE_TYPE_CROSS, MESSAGE_TYPE_HALT,
    _find_order_quantity,
)

MESSAGE_FILE = "data/AAPL_2012-06-21_34200000_57600000_message_5.csv"
ORDERBOOK_FILE = "data/AAPL_2012-06-21_34200000_57600000_orderbook_5.csv"
N_LEVELS = 5
EPSILON = 0.001

BOOK_MODIFYING = (MESSAGE_TYPE_NEW, MESSAGE_TYPE_PARTIAL_CANCEL,
                   MESSAGE_TYPE_EXEC_VISIBLE, MESSAGE_TYPE_DELETE)


def apply_message(engine, msg):
    """Apply one LOBSTER message to the engine."""
    if msg.msg_type == MESSAGE_TYPE_NEW:
        order = Order(
            order_id=msg.order_id, side=msg.side, order_type=OrderType.LIMIT,
            price=msg.price, quantity=msg.size, timestamp=msg.time,
        )
        engine.submit_order(order)

    elif msg.msg_type in (MESSAGE_TYPE_PARTIAL_CANCEL, MESSAGE_TYPE_EXEC_VISIBLE):
        # Both reduce a resting order's size by msg.size.
        #   Type 2 = trader cancels part of their own order.
        #   Type 4 = someone else's marketable order consumed part of it.
        # Type 4 is essential: market orders NEVER appear as Type 1 in
        # LOBSTER. They appear only here, so this is the only path by which
        # liquidity is consumed during replay.
        current_qty = _find_order_quantity(engine, msg.order_id)
        if current_qty is not None:
            new_qty = current_qty - msg.size
            if new_qty > 0:
                engine.modify_order(msg.order_id, new_quantity=new_qty)
            else:
                engine.cancel_order(msg.order_id)

    elif msg.msg_type == MESSAGE_TYPE_DELETE:
        engine.cancel_order(msg.order_id)

    # Type 5 (hidden exec): hit hidden liquidity never in the visible book.
    # Type 6/7 (cross / halt): out of scope.


def engine_qty_at(engine, side, price):
    book = engine.book._book_for(side)
    for p, queue in book.items():
        if abs(p - price) <= EPSILON:
            return sum(o.quantity for o in queue)
    return 0


def lobster_qty_at(snapshot, side, price):
    key = "bids" if side is Side.BUY else "asks"
    for p, q in snapshot[key]:
        if abs(p - price) <= EPSILON:
            return q
    return 0


def run_validation(window_size=500, n_windows=200, verbose=True):
    print("Loading messages and orderbook snapshots...")
    messages = load_messages(MESSAGE_FILE)
    snapshots = load_orderbook(ORDERBOOK_FILE, n_levels=N_LEVELS)
    assert len(messages) == len(snapshots)
    total = len(messages)

    usable = total - window_size - 1
    starts = [int(k * usable / n_windows) for k in range(n_windows)]

    correct_at = [0] * window_size
    scored_at = [0] * window_size

    seen = Counter()          # every message, by type
    skip_reason = Counter()   # why a book-modifying message was not scored
    mismatch_examples = []

    for w, start in enumerate(starts):
        engine = MatchingEngine()

        for offset in range(window_size):
            i = start + 1 + offset
            if i >= total:
                break

            msg = messages[i]
            seen[msg.msg_type] += 1

            if msg.msg_type not in BOOK_MODIFYING:
                apply_message(engine, msg)
                continue

            # Resolve which (side, price) level this message touches, BEFORE
            # applying it.
            if msg.msg_type == MESSAGE_TYPE_NEW:
                side, price = msg.side, round(msg.price, 4)
            else:
                loc = engine.book.order_locations.get(msg.order_id)
                if loc is None:
                    # Cancel/execution against an order our engine never saw
                    # submitted - it was resting before this window opened.
                    skip_reason["order not in our book (pre-window)"] += 1
                    apply_message(engine, msg)
                    continue
                side, price = loc[0], round(loc[1], 4)

            eq_before = engine_qty_at(engine, side, price)
            lq_before = lobster_qty_at(snapshots[i - 1], side, price)

            apply_message(engine, msg)

            eq_after = engine_qty_at(engine, side, price)
            lq_after = lobster_qty_at(snapshots[i], side, price)

            # If the level is outside LOBSTER's visible top-5 on either side of
            # the event, its apparent delta is an artefact of entering/leaving
            # the visible window, not of this event.
            if lq_before == 0 or lq_after == 0:
                skip_reason["level outside LOBSTER top-5 window"] += 1
                continue

            engine_delta = eq_after - eq_before
            lobster_delta = lq_after - lq_before

            scored_at[offset] += 1
            if engine_delta == lobster_delta:
                correct_at[offset] += 1
            elif len(mismatch_examples) < 5:
                mismatch_examples.append({
                    "row": i, "type": msg.msg_type,
                    "side": side.value, "price": price,
                    "engine_delta": engine_delta, "lobster_delta": lobster_delta,
                })

        if verbose and (w + 1) % 25 == 0:
            print(f"...completed window {w + 1}/{n_windows}")

    # ---------------- summary ----------------
    total_scored = sum(scored_at)
    total_correct = sum(correct_at)
    total_book_mod = sum(seen[t] for t in BOOK_MODIFYING)
    total_msgs = sum(seen.values())

    print("\n=== Replay validation (delta matching) ===")
    print(f"{n_windows} windows x {window_size} messages, engine built from messages alone")
    print("Scoring: when LOBSTER's quantity at a level changes, does ours change identically?\n")

    print(f"{'msgs into window':>18} | {'deltas scored':>14} | {'delta match':>13}")
    print("-" * 52)
    checkpoints = [0, 4, 9, 24, 49, 99, 199, 299, 399, window_size - 1]
    for c in checkpoints:
        if c < window_size and scored_at[c] > 0:
            pct = 100 * correct_at[c] / scored_at[c]
            print(f"{c + 1:>18} | {scored_at[c]:>14} | {pct:>12.1f}%")
    overall = 100 * total_correct / max(total_scored, 1)
    print("-" * 52)
    print(f"{'overall':>18} | {total_scored:>14} | {overall:>12.2f}%")

    print("\n--- Coverage ---")
    type_names = {1: "new limit order", 2: "partial cancel", 3: "deletion",
                   4: "visible execution", 5: "hidden execution",
                   6: "cross/auction", 7: "halt"}
    print(f"Total messages processed: {total_msgs}")
    for t in sorted(seen):
        print(f"  type {t} ({type_names.get(t, '?'):<18}): {seen[t]:>7}")
    print(f"\nBook-modifying messages (types 1,2,3,4): {total_book_mod}")
    print(f"  scored: {total_scored} ({100 * total_scored / max(total_book_mod, 1):.1f}%)")
    print(f"  excluded: {total_book_mod - total_scored}")
    for reason, count in skip_reason.most_common():
        pct = 100 * count / max(total_book_mod, 1)
        print(f"    - {reason}: {count} ({pct:.1f}%)")

    if mismatch_examples:
        print("\n--- Example delta mismatches ---")
        for m in mismatch_examples:
            print(f"  row {m['row']} type {m['type']} {m['side']} @ {m['price']}: "
                  f"engine {m['engine_delta']:+d} vs lobster {m['lobster_delta']:+d}")

    print("\nInterpretation: the match rate is the accuracy of event application")
    print("on levels the data lets us verify. The coverage figure states how")
    print("much of the message stream that represents. Excluded events are")
    print("those the file does not contain enough information to check.")

    return {"overall": overall, "scored": total_scored,
            "book_modifying": total_book_mod, "skip_reason": skip_reason}


if __name__ == "__main__":
    run_validation()