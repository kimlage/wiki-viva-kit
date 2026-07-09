from __future__ import annotations

WEB_SNAPSHOT_SCHEMA_VERSION = "wiki_web_snapshot.v2"
WEB_RUNTIME_CONTRACT_VERSION = "wiki_world_runtime.v8"
WEB_BLOCK_VOCABULARY_VERSION = "wiki_blocks.v2"
WEB_VISUAL_GRAMMAR_VERSION = "wiki_visual_grammar.v8"
WEB_SEMANTIC_VISUAL_TOKENS_VERSION = "wiki_semantic_visual_tokens.v1"
WEB_SOURCE_LIFECYCLE_VERSION = "wiki_source_lifecycle.v2"
WEB_SOURCE_FRESHNESS_VERSION = "wiki_source_freshness.v1"
WEB_SOURCE_LAST_ATTEMPT_VERSION = "wiki_source_last_attempt.v1"
WEB_REGISTRY_MODULE_API_VERSION = "wiki_registry_module_api.v1"
WEB_ROUTE_CONTRACT_VERSION = "wiki_world_route.v8"
WEB_RELATION_VOCABULARY_VERSION = "wiki_relation_types.v1"
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
WEB_SERVER_VERSION = "wiki_web_server.v4"
SCHEMA_CAPABILITIES = (
    "operator_security_v1",  # nonce + Host/Origin + bounded/idempotent POST contract
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
    "blocks.json",
    "block_stacks.json",
    "operator_commands.json",
    "work_items.json",
    "region_groups.json",
    "source_lifecycle.json",
    "snapshot_warnings.json",
)
