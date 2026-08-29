"""Period parsing: the one piece of user-controlled text that reaches SQL.

`resolve_interval` turns a fuzzy period from the model into a Postgres interval.
It is a whitelist plus one narrow regex, and anything it does not recognize falls
back to the default window instead of raising. That behaviour is deliberate, so
it is tested explicitly.
"""
from src.queries import resolve_interval


def test_named_periods():
    assert resolve_interval("today") == "1 day"
    assert resolve_interval("7d") == "7 days"
    assert resolve_interval("30d") == "30 days"
    assert resolve_interval("24h") == "24 hours"


def test_case_and_whitespace_are_forgiven():
    assert resolve_interval("  WEEK ") == "7 days"


def test_relative_form():
    assert resolve_interval("14d") == "14 days"
    assert resolve_interval("48h") == "48 hours"


def test_unknown_input_falls_back_instead_of_raising():
    assert resolve_interval(None) == "7 days"
    assert resolve_interval("") == "7 days"
    assert resolve_interval("last fortnight") == "7 days"


def test_injection_attempt_never_reaches_sql():
    """A quote or a statement terminator is not a recognized period, so it is
    dropped at the parser and replaced by the default window."""
    for hostile in [
        "7d'; DROP TABLE channels; --",
        "1 day; DELETE FROM posts_queue",
        "'||(SELECT 1)||'",
        "9999d9",
    ]:
        assert resolve_interval(hostile) == "7 days"
