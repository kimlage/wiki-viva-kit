from __future__ import annotations

from wiki_core.experience_packs import COMPOSITION_SCHEMA_VERSION
from wiki_core.temporal import (
    ACTIVITY_TIMELINE_CONTRACT_VERSION,
    ACTIVITY_TIMELINE_LEGACY_SCHEMA_VERSION,
    TEMPORAL_EVENT_SCHEMA_VERSION,
    TEMPORAL_GRAPH_SCHEMA_VERSION,
)

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
WEB_TIMELINE_SCHEMA_VERSION = ACTIVITY_TIMELINE_LEGACY_SCHEMA_VERSION
WEB_ACTIVITY_TIMELINE_VERSION = ACTIVITY_TIMELINE_CONTRACT_VERSION
WEB_TEMPORAL_EVENT_VERSION = TEMPORAL_EVENT_SCHEMA_VERSION
WEB_TEMPORAL_GRAPH_VERSION = TEMPORAL_GRAPH_SCHEMA_VERSION
WEB_EXPERIENCE_PACK_COMPOSITION_VERSION = COMPOSITION_SCHEMA_VERSION
WEB_DIFF_SCHEMA_VERSION = "wiki_web_diff.v1"

# Operator handshake. server_version bumps when the served API surface changes;
# schema_capabilities lists the feature endpoints this operator serves, so the
# cockpit can detect a stale operator (old process, newer code on disk) and show
# an honest "operador desatualizado — reinicie" state instead of a raw 404. Add
# a capability string here the moment its endpoint ships.
WEB_SERVER_VERSION = "wiki_web_server.v6"
WEB_OPERATOR_SECURITY_VERSION = "wiki_operator_security.v2"
OPERATOR_SECURITY_CAPABILITY = "operator_security_v2"
CORS_DEFAULT_DENY_CAPABILITY = "cors_default_deny_v1"
ACTION_STATE_TRANSITION_CAPABILITY = "action_state_transitions_v1"
SNAPSHOT_PUBLICATION_CAPABILITY = "filesystem_snapshot_publication_v1"
SNAPSHOT_EXTERNAL_FRESHNESS_CAPABILITY = "snapshot_external_freshness_v1"
SOURCE_OPERATIONS_CAPABILITY = "source_operations_v1"
AGENT_ADAPTERS_CAPABILITY = "agent_adapters_v1"
SCHEMA_CAPABILITIES = (
    OPERATOR_SECURITY_CAPABILITY,  # nonce + bounded/idempotent POST + browser-origin policy
    CORS_DEFAULT_DENY_CAPABILITY,  # no browser CORS trust unless exact loopback origins opt in
    "codex",  # /api/codex/capability + /api/codex/jobs
    "briefs",  # /api/briefs
    "gates",  # /api/gates/run (persisted receipts)
    ACTION_STATE_TRANSITION_CAPABILITY,  # /api/actions/transition (domain action pages)
    SNAPSHOT_PUBLICATION_CAPABILITY,  # immutable filesystem revisions + active pointer
    SNAPSHOT_EXTERNAL_FRESHNESS_CAPABILITY,  # live cache observes external writers
    "diff",  # /api/diff/file (per-file full diff)
    "intake",  # /api/intake/copy (add an external file into data/raw)
    "sources",  # /api/sources (entities) + /api/sources/{id}/brief
    SOURCE_OPERATIONS_CAPABILITY,
    AGENT_ADAPTERS_CAPABILITY,
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
    "temporal_graph.json",
    "experience_packs.json",
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
