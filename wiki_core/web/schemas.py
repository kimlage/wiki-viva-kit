from __future__ import annotations

WEB_SNAPSHOT_SCHEMA_VERSION = "wiki_web_snapshot.v1"
WEB_GIT_SCHEMA_VERSION = "wiki_web_git.v1"
WEB_ACTION_SCHEMA_VERSION = "wiki_web_actions.v1"
WEB_GATE_SCHEMA_VERSION = "wiki_web_gates.v1"

SNAPSHOT_FILES = (
    "manifest.json",
    "operations.json",
    "graph.json",
    "pages.json",
    "sources.json",
    "actions.json",
    "decisions.json",
    "freshness.json",
    "gates.json",
    "git.json",
    "ingestion.json",
    "quality.json",
    "commands.json",
)
