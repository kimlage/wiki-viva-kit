"""Shared lifecycle contract for source kinds and update schedules.

This module is deliberately small and deterministic.  Repositories may keep
their own richer recipe parsers and connector implementations while sharing the
same answer to two operational questions: what a source represents, and whether
time alone is allowed to make it stale.
"""

from __future__ import annotations

SOURCE_SCHEDULE_SCHEMA_VERSION = "wiki_source_schedule.v1"
SOURCE_KINDS = frozenset({"item", "collection", "account", "endpoint", "repository"})
SCHEDULE_MODES = frozenset({"one_shot", "on_demand", "recurring", "event_driven"})

_PLATFORM_SOURCE_KINDS = {
    "drive": "collection",
    "file": "collection",
    "google_photos": "collection",
    "repo": "repository",
    "slack": "account",
    "gchat": "account",
    "gmail": "account",
    "calendar": "account",
    "chatgpt": "account",
    "whatsapp": "account",
    "web": "endpoint",
}


def infer_source_kind(platform: str) -> str:
    """Return the conservative source kind used by deterministic migrations."""
    return _PLATFORM_SOURCE_KINDS.get(str(platform or "").strip().lower(), "item")


def validate_source_kind(source_kind: str) -> list[str]:
    """Validate the source-level shape without knowing a repository's recipe."""
    if source_kind in SOURCE_KINDS:
        return []
    return [f"unknown source_kind `{source_kind}` (use {sorted(SOURCE_KINDS)})"]


def validate_schedule(mode: str, cadence_days: int) -> list[str]:
    """Validate when time may create staleness.

    Only recurring sources use a positive cadence. One-shot, on-demand and
    event-driven sources remain current until a new event or explicit operator
    action changes their evidence state.
    """
    if mode not in SCHEDULE_MODES:
        return [f"unknown schedule.mode `{mode}` (use {sorted(SCHEDULE_MODES)})"]
    if mode == "recurring" and cadence_days <= 0:
        return ["a recurring schedule needs a positive cadence_days"]
    if mode != "recurring" and cadence_days != 0:
        return [f"a {mode} schedule must use cadence_days: 0"]
    return []
