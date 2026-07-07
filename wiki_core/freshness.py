"""Single home for the `updated_at` + `stale_after_days` freshness computation.

Every surface that judges whether a page decayed (cockpit snapshot, operation
compiler, audits, operational pass) used to hand-roll the same arithmetic.
The canonical semantics live here and match what the cockpit displays
(`wiki_core/web/snapshot.py`):

- unparseable/missing `updated_at`  -> "unknown"
- `stale_exempt` truthy             -> "fresh" (evergreen: verified once, no decay)
- window (`stale_after_days`) <= 0  -> "unknown"
- otherwise                         -> "stale" iff age exceeds the window

Callers with stricter policies (the audits treat an unparseable date as an
error, the operation compiler computes with a zero window) keep their own
validation and compose the primitives (`parse_updated_date`, `age_days`,
`is_stale`) instead of `freshness_state`.
"""

from __future__ import annotations

import datetime as dt

FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"

_TRUTHY = {"true", "yes", "on", "1"}


def parse_updated_date(value: object) -> dt.date | None:
    """Lenient ISO date parse: accepts `date`/`datetime` objects and strings,
    tolerates a time suffix (only the first 10 chars are read). None on failure."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def age_days(updated_at: object, today: dt.date) -> int | None:
    """Days elapsed since `updated_at` (negative if in the future); None if
    the date cannot be parsed."""
    updated = parse_updated_date(updated_at)
    if updated is None:
        return None
    return (today - updated).days


def is_stale(updated: dt.date, stale_after_days: int, today: dt.date) -> bool:
    """The one comparison everyone shares: the page decayed when its age
    exceeds the declared window (equivalently `updated + window < today`)."""
    return (today - updated).days > stale_after_days


def is_stale_exempt(value: object) -> bool:
    """Truthy-string reading of the `stale_exempt` frontmatter flag."""
    return str(value or "").strip().lower() in _TRUTHY


def freshness_state(
    updated_at: object,
    stale_after_days: object,
    today: dt.date,
    *,
    stale_exempt: bool = False,
) -> str:
    """Canonical freshness verdict: "fresh", "stale" or "unknown"."""
    updated = parse_updated_date(updated_at)
    if updated is None:
        return UNKNOWN
    # Evergreen records (statements, closed events, historical snapshots)
    # opt out of the freshness window: verified once, they do not decay.
    if stale_exempt:
        return FRESH
    try:
        window = int(stale_after_days or 0)
    except (TypeError, ValueError):
        window = 0
    if window <= 0:
        return UNKNOWN
    return STALE if is_stale(updated, window, today) else FRESH
