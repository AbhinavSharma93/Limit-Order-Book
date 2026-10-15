

from src.matching_engine import MatchingEngine
from src.lobster_parser import load_messages, load_orderbook, replay_messages

MESSAGE_FILE = "data/AAPL_2012-06-21_34200000_57600000_message_5.csv"
ORDERBOOK_FILE = "data/AAPL_2012-06-21_34200000_57600000_orderbook_5.csv"


def test_load_messages_basic():
    messages = load_messages(MESSAGE_FILE)
    assert len(messages) > 0
    first = messages[0]
    assert first.msg_type in (1, 2, 3, 4, 5, 6, 7)
    assert isinstance(first.price, float)
    print(f"load_messages_basic: OK ({len(messages)} rows)")


def test_load_orderbook_basic():
    snapshots = load_orderbook(ORDERBOOK_FILE, n_levels=5)
    assert len(snapshots) > 0
    assert len(snapshots[0]["asks"]) == 5
    assert len(snapshots[0]["bids"]) == 5
    print(f"load_orderbook_basic: OK ({len(snapshots)} rows)")


def test_message_orderbook_row_alignment():
    messages = load_messages(MESSAGE_FILE)
    snapshots = load_orderbook(ORDERBOOK_FILE, n_levels=5)
    assert len(messages) == len(snapshots)   # row-for-row alignment
    print("message_orderbook_row_alignment: OK")


def test_replay_small_slice_runs():
    messages = load_messages(MESSAGE_FILE)
    engine = MatchingEngine()
    stats = replay_messages(engine, messages[:2000])   # small slice for speed
    print("replay stats:", {k: v for k, v in stats.items() if k != "warnings"})
    print(f"warnings: {len(stats['warnings'])}")
    print("replay_small_slice_runs: OK")


if __name__ == "__main__":
    test_load_messages_basic()
    test_load_orderbook_basic()
    test_message_orderbook_row_alignment()
    test_replay_small_slice_runs()
    print("All lobster_parser tests passed.")