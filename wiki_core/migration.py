from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wiki_core.config import WikiConfig, freshness_for
from wiki_core.ids import slugify
from wiki_core.page_types import PageTypeRegistry


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)

DIR_PAGE_TYPE_HINTS = {
    "actions": "action",
    "acoes": "action",
    "assignments": "assignment",
    "atribuicoes": "assignment",
    "claims": "claim",
    "coverage": "coverage",
    "cobertura": "coverage",
    "decisions": "decision",
    "decisoes": "decision",
    "evidence": "evidence",
    "evidencias": "evidence",
    "holons": "holon",
    "initiatives": "initiative",
    "iniciativas": "initiative",
    "insights": "insight",
    "analyses": "insight",
    "analises": "insight",
    "contexts": "context_note",
    "contextos": "context_note",
    "meetings": "meeting",
    "reunioes": "meeting",
    "people": "person",
    "pessoas": "person",
    "projects": "project",
    "projetos": "project",
    "responsibilities": "responsibility",
    "responsabilidades": "responsibility",
    "roles": "role",
    "papeis": "role",
    "rules": "operational_rule",
    "regras": "operational_rule",
    "sources": "source",
    "fontes": "source",
    "timelines": "timeline",
}

DATED_OPERATIONAL_FILENAME_RE = re.compile(r"^20\d{2}-\d{2}(?:-\d{2})?(?:[-_.].*)?\.md$")


@dataclass(frozen=True)
class MigrationSuggestion:
    rel: str
    issue: str
    title: str
    context: str
    page_type: str
    page_id: str
    updated_at: str
    stale_after_days: str
    reason: str


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    data = yaml.safe_load(match.group(1)) or {}
    values = data if isinstance(data, dict) else {}
    return values, text[match.end() :]


def title_from_markdown(text: str, fallback: str) -> str:
    _frontmatter, body = split_frontmatter(text)
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return fallback


def infer_context(rel: str, config: WikiConfig) -> str:
    parts = Path(rel).parts
    memory_root = str(config.paths.get("memory_root") or "memories").strip("/")
    system_dirname = str(config.paths.get("system_dirname") or "system").strip("/")
    if not parts or parts[0] != memory_root:
        return config.default_context
    if len(parts) > 1:
        candidate = parts[1]
        if candidate in config.contexts:
            return candidate
        if candidate == system_dirname:
            return config.default_context
    return config.default_context


def infer_page_type(rel: str, config: WikiConfig, registry: PageTypeRegistry | None = None) -> tuple[str, str]:
    parts = Path(rel).parts
    memory_root = str(config.paths.get("memory_root") or "memories").strip("/")
    filename = parts[-1] if parts else ""
    available = set(registry.page_types) if registry else set()

    if rel == f"{memory_root}/index.md":
        return "root_index", "root memory index"

    if filename in {"index.md", "README.md"}:
        return "context_hub", "index/readme page"

    for part in parts[1:-1]:
        hinted = DIR_PAGE_TYPE_HINTS.get(part)
        if hinted and (not available or hinted in available):
            return hinted, f"directory hint `{part}`"

    if DATED_OPERATIONAL_FILENAME_RE.match(filename) and ("monthly_closing" in available or not available):
        return "monthly_closing", "dated operational page"

    return "context_note", "fallback for legacy page without a stronger hint"


def suggest_frontmatter_for_legacy_page(
    root: Path,
    rel: str,
    config: WikiConfig,
    registry: PageTypeRegistry | None = None,
    today: dt.date | None = None,
) -> MigrationSuggestion | None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    values, _body = split_frontmatter(text)
    if values is not None:
        return None
    today = today or dt.date.today()
    title = title_from_markdown(text, Path(rel).stem.replace("-", " ").replace("_", " ").title())
    context = infer_context(rel, config)
    page_type, reason = infer_page_type(rel, config, registry)
    return MigrationSuggestion(
        rel=rel,
        issue="missing_frontmatter",
        title=title,
        context=context,
        page_type=page_type,
        page_id=f"{slugify(page_type)}-{slugify(title)}",
        updated_at=today.isoformat(),
        stale_after_days=str(freshness_for(context, page_type, config)),
        reason=reason,
    )


def migration_inventory(
    root: Path,
    config: WikiConfig,
    registry: PageTypeRegistry | None = None,
    today: dt.date | None = None,
) -> list[MigrationSuggestion]:
    memory_root = root / str(config.paths.get("memory_root") or "memories")
    if not memory_root.exists():
        return []
    suggestions: list[MigrationSuggestion] = []
    for path in sorted(memory_root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        suggestion = suggest_frontmatter_for_legacy_page(root, rel, config, registry, today=today)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def frontmatter_block_for_suggestion(
    suggestion: MigrationSuggestion,
    *,
    visibility: str,
    gate: str,
) -> str:
    data = {
        "page_id": suggestion.page_id,
        "page_type": suggestion.page_type,
        "context": suggestion.context,
        "visibility": visibility,
        "updated_at": suggestion.updated_at,
        "stale_after_days": suggestion.stale_after_days,
        "gate": gate,
    }
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---"
