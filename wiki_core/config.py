from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# The config drives the honesty gates, so it is parsed with PyYAML (the same
# engine as every other YAML in the toolkit) and then a STRICT validation layer
# (language/contexts/booleans) runs on top. Malformed values in those key fields
# FAIL LOUD instead of silently disabling verification.

_BOOL_TRUE = {"true", "yes", "on", "1"}
_BOOL_FALSE = {"false", "no", "off", "0"}
_LANGUAGE_RE = re.compile(r"[a-z]{2,8}")
_CONTEXT_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load the config file as a mapping via ``yaml.safe_load``.

    Replaces the former home-grown ``_simple_yaml``. PyYAML natively handles the
    shapes the hand-rolled parser supported (inline comments outside quotes,
    single/double quotes, YAML lists, nested maps, case-insensitive booleans and
    integers) and more, while the strict layer below keeps the gate-critical
    fields honest.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _as_bool(value: Any, *, field_name: str) -> bool:
    """Convert a config value into bool, failing LOUD if ambiguous.

    Never uses bool(str) — 'False'/'no'/'"false"' silently became True and
    disabled strict PII mode without the owner noticing.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        low = value.strip().strip("\"'").lower()
        if low in _BOOL_TRUE:
            return True
        if low in _BOOL_FALSE:
            return False
    raise ValueError(
        f"config: invalid boolean field {field_name!r}: {value!r} "
        f"(use true/false/yes/no/on/off)"
    )


def _parse_contexts(raw_value: Any) -> tuple[str, ...]:
    """Accept a YAML list OR a comma-separated string; validate each slug.

    Rejects garbage like '{}' (symptom of the old discarded-list bug) instead of
    silently requiring '<memory_root>/{}/index.md' in the auditor.
    """
    if isinstance(raw_value, (list, tuple)):
        items = [str(c).strip() for c in raw_value]
    elif isinstance(raw_value, str):
        items = [c.strip() for c in raw_value.split(",")]
    elif raw_value in (None, {}):
        items = []
    else:
        raise ValueError(
            f"config: invalid 'contexts': {raw_value!r} "
            f"(use a YAML list or comma-separated values)"
        )
    contexts = tuple(c for c in items if c)
    for c in contexts:
        if not _CONTEXT_SLUG_RE.fullmatch(c):
            raise ValueError(
                f"config: invalid context: {c!r} "
                f"(expected lowercase slug [a-z0-9-], e.g. finance)"
            )
    return contexts


@dataclass(frozen=True)
class WikiConfig:
    repo_id: str = "wiki-repo"
    owner_label: str = "Owner"
    # Project language (e.g. "en", "pt"). Drives the GENERATED output (cockpit,
    # proposals) — the code reads per-language string tables. Default: "en".
    language: str = "en"
    default_visibility: str = "private_self"
    private_sensitive_allowed: bool = True
    # Memory contexts that must have a `<memory_root>/<ctx>/index.md` hub. Drives
    # which context pages the auditor requires -- portable per repo, no hardcode.
    contexts: tuple[str, ...] = ()
    # Context slug used by generators when none is given (--context defaults,
    # cockpit frontmatter, score events). Localized repos pin it (e.g. "sistema").
    default_context: str = "system"
    # Repo layout. English defaults; a repo with localized directory names pins
    # every key it renames. *_dirname keys are single path segments composed by
    # WikiPaths; *_page keys are full repo-relative paths.
    paths: dict[str, str] = field(
        default_factory=lambda: {
            "memory_root": "memories",
            "references_root": "docs/references",
            "raw_root": "data/raw",
            "derived_root": "data/derived/wiki",
            "skills_root": ".skills",
            "system_dirname": "system",
            "ingest_dirname": "ingestion",
            "events_dirname": "events",
            "archive_dirname": "archive",
            "decisions_dirname": "decisions",
            "actions_dirname": "actions",
            "pending_actions_filename": "pending.md",
            "sources_dirname": "sources",
            "operation_page": "memories/operations.md",
            "operational_pass_page": "memories/system/operational-pass.md",
            "command_reference_page": "memories/system/wiki/command-reference.md",
            "wiki_coverage_page": "memories/system/wiki-coverage.md",
            "source_registry_page": "memories/system/source-registry.md",
        }
    )
    # Methodology-coverage gate targets (wiki_check_methodology_coverage.py).
    # required_templates are filenames under <references_root>/templates/wiki.
    coverage: dict[str, Any] = field(
        default_factory=lambda: {
            "methodology_source_page": "memories/sources/wiki-viva-methodology-v5.md",
            "coverage_matrix_page": "memories/system/methodology-coverage-v5.md",
            "required_templates": [
                "ingestion-event.md",
                "operation.md",
                "vitality-dashboard.md",
                "subagent-brief.md",
                "gate.md",
            ],
        }
    )
    approval: dict[str, Any] = field(
        default_factory=lambda: {
            "gate": "github_pr",
            "branch_prefix": "wiki/",
            "require_operation_update": True,
            "require_log_update": True,
        }
    )
    llm: dict[str, Any] = field(
        default_factory=lambda: {
            "required_context_pass": True,
            "cache_enabled": True,
            "default_model_profile": "deep_context",
            "chunk_target_tokens": 1200,
            "chunk_overlap_tokens": 150,
            "prompt_versions": {
                "manifest_review": "v1",
                "context_deep_read": "v1",
                "quadrant_extraction": "v1",
                "crm_relationships": "v1",
                "operation_compile": "v1",
                "decision_action_synthesis": "v1",
            },
        }
    )
    # Per-context page freshness (stale_after_days). CONTEXT drives the update
    # cadence: a fast-moving context gets a short window, a reference context a
    # long one. `default` applies when a context is not listed; a `type:<page_type>`
    # key (optional) overrides per page type. Generators read this via
    # freshness_for(); localized repos pin their own contexts' windows.
    freshness: dict[str, int] = field(default_factory=lambda: {"default": 30})
    templates: dict[str, Any] = field(
        default_factory=lambda: {
            "overlays_root": "docs/references/templates/overlays",
            "page_type_overrides": {},
        }
    )
    # Optional semantic entry point for repos adopting the integral root model.
    # Existing repos without this block keep the old context/source behavior.
    root_entity: dict[str, Any] = field(
        default_factory=lambda: {
            "page": "",
            "entity_type": "",
            "input_stage_page": "memories/system/input-stage.md",
            "perspective_bundle": {"required": [], "optional": []},
            "default_target_strategy": "root_then_context_hub",
        }
    )
    audit: dict[str, Any] = field(
        default_factory=lambda: {
            # Pages every wiki repo must keep tracked (wiki_audit core gate).
            "core_pages": [
                "memories/index.md",
                "memories/system/log.md",
                "memories/system/docs-review.md",
                "memories/system/operational-wiki-contract.md",
                "memories/system/ingestion-process.md",
                "memories/system/git-approvals.md",
                "memories/system/wiki-coverage.md",
                "memories/system/ingestion/README.md",
                "memories/system/source-registry.md",
            ],
            # Pages allowed to mention retired/legacy paths (e.g. migration docs).
            "allowed_old_path_references": [
                ".github/pull_request_template.md",
                "docs/references/templates/wiki/pr-checklist.md",
            ],
        }
    )
    # Operational karma (gamification layer). Opt-in feature, ENABLED by default
    # in the kit so existing repos keep their cockpit unchanged; a repo turns it
    # off with `karma:\n  enabled: false` in wiki.config.yaml (then wiki_score is a
    # no-op and the cockpit omits the karma/score section).
    karma: dict[str, Any] = field(default_factory=lambda: {"enabled": True})

    @property
    def karma_enabled(self) -> bool:
        value = self.karma.get("enabled", True)
        if isinstance(value, bool):
            return value
        return _as_bool(value, field_name="karma.enabled")


def load_config(root: Path) -> WikiConfig:
    path = root / "wiki.config.yaml"
    if not path.exists():
        return WikiConfig()
    raw = _load_yaml_mapping(path)

    language = str(raw.get("language", "en")).strip().strip("\"'")
    if not _LANGUAGE_RE.fullmatch(language):
        raise ValueError(
            f"config: invalid language: {language!r} "
            f"(expected lowercase code of 2-8 letters, e.g. pt, en)"
        )

    contexts = _parse_contexts(raw.get("contexts", ""))

    default_context = str(raw.get("default_context", "system")).strip().strip("\"'")
    if not _CONTEXT_SLUG_RE.fullmatch(default_context):
        raise ValueError(
            f"config: invalid default_context: {default_context!r} "
            f"(expected lowercase slug [a-z0-9-], e.g. system)"
        )

    return WikiConfig(
        repo_id=str(raw.get("repo_id", "wiki-repo")),
        owner_label=str(raw.get("owner_label", "Owner")),
        language=language,
        default_visibility=str(raw.get("default_visibility", "private_self")),
        private_sensitive_allowed=_as_bool(
            raw.get("private_sensitive_allowed", True),
            field_name="private_sensitive_allowed",
        ),
        contexts=contexts,
        default_context=default_context,
        paths={**WikiConfig().paths, **dict(raw.get("paths", {}))},
        approval={**WikiConfig().approval, **dict(raw.get("approval", {}))},
        llm={**WikiConfig().llm, **dict(raw.get("llm", {}))},
        coverage={**WikiConfig().coverage, **dict(raw.get("coverage", {}))},
        freshness={
            **WikiConfig().freshness,
            **{str(k): v for k, v in dict(raw.get("freshness", {})).items()},
        },
        templates={**WikiConfig().templates, **dict(raw.get("templates", {}))},
        root_entity={**WikiConfig().root_entity, **dict(raw.get("root_entity", {}))},
        audit={**WikiConfig().audit, **dict(raw.get("audit", {}))},
        karma={**WikiConfig().karma, **dict(raw.get("karma", {}))},
    )


def freshness_for(context: str, page_type: str, config: WikiConfig) -> int:
    """stale_after_days for a page, driven by its CONTEXT (context determines the
    update cadence). A `type:<page_type>` key overrides a context key; `default` is
    the fallback. Always returns a positive int."""
    fr = config.freshness
    for key in (f"type:{page_type}", context, "default"):
        if key in fr:
            try:
                days = int(fr[key])
            except (TypeError, ValueError):
                continue
            if days > 0:
                return days
    return 30
