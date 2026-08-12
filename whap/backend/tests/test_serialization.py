"""WP8 - serialization correctness.

to_dict() emitted ``isoformat() + 'Z'``. For a naive UTC value that's fine, but
for a timezone-aware value isoformat() already ends in ``+00:00``, so the result
was the invalid ``...+00:00Z`` that datetime.fromisoformat cannot parse. The
output must be valid ISO-8601 whether the underlying value is naive or aware.
"""
from datetime import datetime, timezone
from app.models import LocalUser


def _assert_valid_iso_utc(value):
    assert isinstance(value, str)
    # Must parse, and must not carry a doubled UTC marker.
    assert not value.endswith("+00:00Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_to_dict_created_at_is_valid_for_fresh_aware_object(app):
    """A freshly-built object holds an *aware* created_at (the default lambda),
    which previously produced an invalid ...+00:00Z string."""
    user = LocalUser(username="fresh")
    user.created_at = datetime.now(timezone.utc)  # aware, as the default sets it
    _assert_valid_iso_utc(user.to_dict()["created_at"])


def test_to_dict_created_at_is_valid_for_naive_value(app):
    user = LocalUser(username="naive")
    user.created_at = datetime(2026, 1, 1, 12, 0, 0)  # naive UTC (as read from DB)
    _assert_valid_iso_utc(user.to_dict()["created_at"])


def test_to_dict_handles_none_created_at(app):
    user = LocalUser(username="nulldate")
    user.created_at = None
    # Must not raise; None is acceptable in the payload.
    assert user.to_dict().get("created_at") in (None,)
