from __future__ import annotations

WEB_SNAPSHOT_SCHEMA_VERSION = "wiki_web_snapshot.v1"
WEB_GIT_SCHEMA_VERSION = "wiki_web_git.v1"
WEB_ACTION_SCHEMA_VERSION = "wiki_web_actions.v1"
WEB_GATE_SCHEMA_VERSION = "wiki_web_gates.v1"
WEB_TIMELINE_SCHEMA_VERSION = "wiki_web_timeline.v1"
WEB_DIFF_SCHEMA_VERSION = "wiki_web_diff.v1"

# Operator handshake. server_version bumps when the served API surface changes;
# schema_capabilities lists the feature endpoints this operator serves, so the
# cockpit can detect a stale operator (old process, newer code on disk) and show
# an honest "operador desatualizado — reinicie" state instead of a raw 404. Add
# a capability string here the moment its endpoint ships.
WEB_SERVER_VERSION = "wiki_web_server.v3"
SCHEMA_CAPABILITIES = (
    "codex",  # /api/codex/capability + /api/codex/jobs
    "briefs",  # /api/briefs
    "gates",  # /api/gates/run (persisted receipts)
    "diff",  # /api/diff/file (per-file full diff)
    "intake",  # /api/intake/copy (add an external file into data/raw)
    "sources",  # /api/sources (entities) + /api/sources/{id}/brief
)

SNAPSHOT_FILES = (
    "manifest.json",
    "operations.json",
    "graph.json",
    "pages.json",
    "sources.json",
    "source_entities.json",
    "templates.json",
    "actions.json",
    "decisions.json",
    "freshness.json",
    "gates.json",
    "git.json",
    "timeline.json",
    "diff.json",
    "ingestion.json",
    "quality.json",
    "commands.json",
    "score.json",
)
