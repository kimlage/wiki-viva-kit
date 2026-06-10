from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Home-grown but ROBUST config parser: the config drives the honesty gates,
# so common YAML shapes must not silently disable verification. Supports:
# inline comment (outside quotes), single/double quotes, YAML lists ('- item'),
# case-insensitive booleans (true/false/yes/no/on/off) and integers. Malformed
# values in key fields (language, contexts, booleans) FAIL LOUD.

_BOOL_TRUE = {"true", "yes", "on", "1"}
_BOOL_FALSE = {"false", "no", "off", "0"}
_LANGUAGE_RE = re.compile(r"[a-z]{2,8}")
_CONTEXT_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _strip_inline_comment(raw: str) -> str:
    """Remove a '# ...' comment outside quotes, preserving indentation.

    In YAML, '#' only starts a comment when it is at the beginning of the line
    or preceded by space/tab; a '#' glued to a character (e.g. hex color) is literal.
    """
    out: list[str] = []
    quote: str | None = None
    for i, c in enumerate(raw):
        if quote is not None:
            out.append(c)
            if c == quote:
                quote = None
            continue
        if c in ('"', "'"):
            quote = c
            out.append(c)
            continue
        if c == "#" and (i == 0 or raw[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


def _coerce(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    low = value.lower()
    # Boolean words become bool; "1"/"0" do NOT (they are integers in general parsing).
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _simple_yaml(path: Path) -> dict[str, Any]:
    """Restricted but honest YAML: nested maps by indentation + lists.

    Each stack frame holds (indent, kind, container, parent, key). A list item
    ('- x') converts the empty map just opened by its key into a list,
    supporting both the indented form and the form at the same level as the key.
    """
    root: dict[str, Any] = {}
    stack: list[dict[str, Any]] = [
        {"indent": -1, "kind": "map", "container": root, "parent": None, "key": None}
    ]
    for raw in path.read_text(encoding="utf-8").splitlines():
        content = _strip_inline_comment(raw)
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        line = content.strip()

        if line.startswith("- "):
            item = _coerce(line[2:].strip())
            # List items attach to the key whose indent is <= the item's (YAML
            # allows the list at the same level as the key): we only pop frames
            # that are STRICTLY shallower.
            while len(stack) > 1 and indent < stack[-1]["indent"]:
                stack.pop()
            top = stack[-1]
            if top["kind"] == "map" and top["parent"] is not None and not top["container"]:
                new_list: list[Any] = []
                top["parent"][top["key"]] = new_list
                top["kind"] = "list"
                top["container"] = new_list
            if top["kind"] == "list":
                top["container"].append(item)
            continue

        if ":" not in line:
            continue
        # Keys pop frames at the same level or shallower.
        while len(stack) > 1 and indent <= stack[-1]["indent"]:
            stack.pop()
        top = stack[-1]
        if top["kind"] != "map":
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            top["container"][key] = _coerce(value)
        else:
            child: dict[str, Any] = {}
            top["container"][key] = child
            stack.append(
                {
                    "indent": indent,
                    "kind": "map",
                    "container": child,
                    "parent": top["container"],
                    "key": key,
                }
            )
    return root


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
            "command_reference_page": "memories/system/wiki/command-reference.md",
            "wiki_coverage_page": "memories/system/wiki-coverage.md",
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
            ],
            # Pages allowed to mention retired/legacy paths (e.g. migration docs).
            "allowed_old_path_references": [
                ".github/pull_request_template.md",
                "docs/references/templates/wiki/pr-checklist.md",
            ],
        }
    )


def load_config(root: Path) -> WikiConfig:
    path = root / "wiki.config.yaml"
    if not path.exists():
        return WikiConfig()
    raw = _simple_yaml(path)

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
        audit={**WikiConfig().audit, **dict(raw.get("audit", {}))},
    )
