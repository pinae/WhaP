"""Helpers for consuming the Redis ``job_updates_queue``.

The producer (``run_job.py``) pushes updates with ``LPUSH`` (onto the head of
the list). To consume them in the order they were produced (FIFO) we must pop
from the *tail* with ``BRPOP``/``RPOP`` -- popping from the head (``BLPOP``/
``LPOP``) would yield LIFO order, reversing log lines and letting a final-status
event overtake the stdout that preceded it.

``drain_batch`` is deliberately pure (it only talks to a Redis-shaped client and
returns the raw payload strings), so it can be unit-tested with an in-memory
fake and reused by the consumer loop in ``run.py``.
"""


def drain_batch(client, key, max_size, block_timeout):
    """Block until at least one update is available, then drain a FIFO batch.

    Args:
        client: a Redis client (real or a test double) exposing ``brpop``,
            ``rpop`` and ``llen``.
        key: the queue key.
        max_size: maximum number of items to return in one batch.
        block_timeout: seconds to block waiting for the first item. A finite
            value (not 0) keeps the connection from blocking indefinitely, so
            an idle-dropped socket is detected promptly and the client can
            reconnect on the next call.

    Returns:
        A list of raw payload strings in production (FIFO) order. Empty when the
        block window elapsed with nothing queued (a normal idle tick, not an
        error).
    """
    first = client.brpop(key, timeout=block_timeout)
    if first is None:
        return []

    # redis-py returns (key, value) for brpop; tolerate a bare value too.
    payload = first[1] if isinstance(first, (tuple, list)) else first
    batch = [payload]

    # Drain whatever else is already queued, newest-waits, oldest-first.
    while len(batch) < max_size and client.llen(key) > 0:
        nxt = client.rpop(key)
        if nxt is None:
            break
        batch.append(nxt)

    return batch
