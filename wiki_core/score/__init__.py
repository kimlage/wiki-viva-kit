"""Gamification layer: operational karma + context vitality.

Re-exports the public API of `wiki_core.score.karma` (Section 13 of the v5 methodology).
"""

from __future__ import annotations

from .karma import (
    BADGES,
    DIMENSIONS,
    EVENT_TYPES,
    LEVELS,
    Badge,
    ScoreEvent,
    build_event,
    compute_karma,
    context_vitality,
    earned_badges,
    level_for,
    load_events,
    mirror_events,
    record_event,
    resolve_events_path,
)

__all__ = [
    "ScoreEvent",
    "Badge",
    "DIMENSIONS",
    "EVENT_TYPES",
    "BADGES",
    "LEVELS",
    "record_event",
    "build_event",
    "load_events",
    "resolve_events_path",
    "mirror_events",
    "compute_karma",
    "context_vitality",
    "earned_badges",
    "level_for",
]
