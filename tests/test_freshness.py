"""Canonical freshness semantics (wiki_core/freshness.py) — the single home
for the updated_at + stale_after_days computation that the cockpit displays."""

from __future__ import annotations

import datetime as dt

from wiki_core.freshness import (
    age_days,
    freshness_state,
    is_stale,
    is_stale_exempt,
    parse_updated_date,
)

TODAY = dt.date(2026, 7, 7)


def test_freshness_state_core_verdicts() -> None:
    assert freshness_state("2026-07-01", "30", TODAY) == "fresh"
    assert freshness_state("2026-05-01", "30", TODAY) == "stale"
    # Boundary: exactly at the window is still fresh (strict > comparison).
    assert freshness_state("2026-06-07", "30", TODAY) == "fresh"
    assert freshness_state("2026-06-06", "30", TODAY) == "stale"


def test_freshness_state_unknowns() -> None:
    assert freshness_state("", "30", TODAY) == "unknown"
    assert freshness_state(None, "30", TODAY) == "unknown"
    assert freshness_state("not-a-date", "30", TODAY) == "unknown"
    # No declared window (or a non-positive one) -> no verdict.
    assert freshness_state("2026-01-01", "", TODAY) == "unknown"
    assert freshness_state("2026-01-01", "0", TODAY) == "unknown"
    assert freshness_state("2026-01-01", "abc", TODAY) == "unknown"


def test_freshness_state_stale_exempt_is_evergreen() -> None:
    assert freshness_state("2020-01-01", "7", TODAY, stale_exempt=True) == "fresh"
    # But an unparseable date stays unknown even when exempt (snapshot semantics).
    assert freshness_state("", "7", TODAY, stale_exempt=True) == "unknown"


def test_parse_updated_date_tolerates_time_suffix_and_objects() -> None:
    assert parse_updated_date("2026-07-02") == dt.date(2026, 7, 2)
    assert parse_updated_date("2026-07-02T10:30:00Z") == dt.date(2026, 7, 2)
    assert parse_updated_date(dt.date(2026, 7, 2)) == dt.date(2026, 7, 2)
    assert parse_updated_date(dt.datetime(2026, 7, 2, 10, 30)) == dt.date(2026, 7, 2)
    assert parse_updated_date("") is None
    assert parse_updated_date("2026-13-40") is None


def test_age_days_and_is_stale() -> None:
    assert age_days("2026-07-01", TODAY) == 6
    assert age_days("bogus", TODAY) is None
    assert is_stale(dt.date(2026, 7, 1), 5, TODAY) is True
    assert is_stale(dt.date(2026, 7, 1), 6, TODAY) is False


def test_is_stale_exempt_truthy_strings() -> None:
    assert is_stale_exempt("true")
    assert is_stale_exempt("Yes")
    assert is_stale_exempt(True)
    assert not is_stale_exempt("false")
    assert not is_stale_exempt("")
    assert not is_stale_exempt(None)
