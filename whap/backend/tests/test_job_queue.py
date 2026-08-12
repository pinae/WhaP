"""Tests for the job-updates queue drain logic (``app.job_queue.drain_batch``).

These pin the FIFO contract that was previously broken: the producer LPUSHes,
so the consumer must pop from the tail to preserve production order. They use a
tiny in-memory Redis double, so no Redis server (or app context) is needed.
"""
from app.job_queue import drain_batch


class FakeRedis:
    """Minimal list-only Redis double: LPUSH (head), RPOP/BRPOP (tail), LLEN."""

    def __init__(self):
        self.store = {}

    def lpush(self, key, *values):
        lst = self.store.setdefault(key, [])
        for v in values:
            lst.insert(0, v)  # push onto the head, like Redis LPUSH
        return len(lst)

    def rpop(self, key):
        lst = self.store.get(key, [])
        return lst.pop() if lst else None  # pop from the tail

    def brpop(self, key, timeout=0):
        lst = self.store.get(key, [])
        if not lst:
            return None  # simulate the block-timeout elapsing with nothing queued
        return (key, lst.pop())

    def llen(self, key):
        return len(self.store.get(key, []))


def test_drain_batch_preserves_production_order():
    r = FakeRedis()
    for payload in ["A", "B", "C"]:  # produced in this order via LPUSH
        r.lpush("q", payload)

    assert drain_batch(r, "q", max_size=50, block_timeout=1) == ["A", "B", "C"]


def test_drain_batch_empty_queue_is_idle_not_error():
    r = FakeRedis()
    assert drain_batch(r, "q", max_size=50, block_timeout=1) == []


def test_drain_batch_respects_max_size_and_leaves_remainder():
    r = FakeRedis()
    for payload in [str(i) for i in range(10)]:  # produced 0,1,...,9
        r.lpush("q", payload)

    batch = drain_batch(r, "q", max_size=3, block_timeout=1)

    assert batch == ["0", "1", "2"]  # oldest first, capped
    assert r.llen("q") == 7  # the rest stay queued, in order


def test_drain_batch_tolerates_bare_value_from_brpop():
    class BareValueRedis(FakeRedis):
        def brpop(self, key, timeout=0):
            lst = self.store.get(key, [])
            return lst.pop() if lst else None  # value only, no (key, value) tuple

    r = BareValueRedis()
    r.lpush("q", "only")
    assert drain_batch(r, "q", max_size=50, block_timeout=1) == ["only"]
