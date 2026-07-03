"""Assisted source migration — bring legacy source pages up to the source-entity
contract and scaffold the ingestion recipe where a ``source_config`` page has
none.

The transformation is **deterministic, additive-only, and dry-run-first**: it
only *adds* missing keys (never overwrites a value the owner already wrote) and,
where it cannot infer a value, it writes an explicit ``TODO`` placeholder plus a
note — it NEVER invents data. Every applied change is meant to flow through the
normal PR gate for a human to complete and approve.

What it does:

* ``source`` pages gain ``platform`` / ``source_locator`` / ``owner`` (inferred
  from the page, its ``config_ref`` page, or a conservative fallback) and a
  ``sync`` machine block seeded to ``never`` (honest: nothing has synced yet).
* ``source_config`` pages with no fenced ``recipe:`` block gain a scaffolded one
  (platform + locator + one content pipeline + a TODO stream) so an agent has a
  manual to complete.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import FRONTMATTER_RE, parse_frontmatter
from wiki_core.source_recipe import PLATFORMS, extract_recipe_mapping

SOURCE_MIGRATION_SCHEMA_VERSION = "wiki_source_migration.v1"

# source_type (or a co-located hint) -> platform. Anything unmapped falls back
# to "manual" (a valid platform meaning human-curated / no automated pull), with
# a note so the reviewer confirms it.
_SOURCE_TYPE_PLATFORM: dict[str, str] = {
    "reference": "repo",
    "repository": "repo",
    "repo": "repo",
    "document": "file",
    "file": "file",
    "export": "file",
    "dataset": "file",
    "feed": "web",
    "website": "web",
    "web": "web",
    "chat": "slack",
    "conversation": "slack",
    "email": "gmail",
    "calendar": "calendar",
}

# Platforms whose locator is a repo-local path (so the page's own path is a
# legitimate, non-invented locator). Chat/web platforms need a real external id,
# which we leave as an explicit TODO.
_REPO_LOCATOR_PLATFORMS = frozenset({"repo", "file", "manual"})


@dataclass(frozen=True)
class SourceMigrationChange:
    """One additive change to one source/source_config page."""

    rel: str
    page_type: str
    add_frontmatter: dict[str, Any] = field(default_factory=dict)
    append_recipe: str = ""
    notes: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not self.add_frontmatter and not self.append_recipe


def infer_platform(values: dict[str, Any]) -> tuple[str, bool]:
    """Return (platform, guessed). ``guessed`` marks a conservative fallback the
    reviewer should confirm."""
    existing = str(values.get("platform") or "").strip()
    if existing in PLATFORMS:
        return existing, False
    source_type = str(values.get("source_type") or "").strip().lower()
    mapped = _SOURCE_TYPE_PLATFORM.get(source_type)
    if mapped:
        # A chat/email mapping from a coarse source_type is a real guess.
        return mapped, source_type in {"chat", "conversation", "email"}
    return "manual", True


def infer_locator(rel: str, values: dict[str, Any], platform: str) -> tuple[str, bool]:
    """Return (locator, is_todo). Repo-local platforms use the page path; external
    platforms get an explicit TODO placeholder (never a fabricated id)."""
    existing = str(values.get("source_locator") or "").strip()
    if existing:
        return existing, False
    url = str(values.get("url") or values.get("source_url") or "").strip()
    if platform == "web" and url:
        return url, False
    if platform in _REPO_LOCATOR_PLATFORMS:
        return rel, False
    return f"TODO-{platform}-locator", True


def _contained(root: Path, rel: str) -> Path | None:
    """Resolve a repo-relative path and refuse anything that escapes the repo
    root (``../`` or absolute) — a config_ref must never read arbitrary files."""
    candidate = Path(rel)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _config_page_values(root: Path, values: dict[str, Any]) -> dict[str, Any]:
    config_ref = str(values.get("config_ref") or "").strip()
    if not config_ref:
        return {}
    path = _contained(root, config_ref)
    if path is None or not path.is_file():
        return {}
    return parse_frontmatter(path)[0]


def infer_owner(values: dict[str, Any], config_values: dict[str, Any]) -> str:
    """Owner from the page, else the governing config page. Never fabricated."""
    existing = str(values.get("owner") or "").strip()
    if existing:
        return existing
    return str(config_values.get("owner") or "").strip()


def scaffold_recipe_block(platform: str, locator: str) -> str:
    """A valid-but-placeholder recipe manual. All open decisions are TODOs the
    reviewer completes; the stream is unselected so nothing ingests by accident."""
    recipe = {
        "recipe": {
            "schema_version": "wiki_source_recipe.v1",
            "platform": platform,
            "locator": locator,
            "pipelines": [{"kind": "content", "cadence_days": 30}],
            "streams": [
                {
                    "id": "todo-stream-1",
                    "label": "TODO: name the channel / folder / export",
                    "selected": False,
                    "privacy": "private_self",
                    "skip_reason": "TODO: set filters + privacy, then select to enable",
                }
            ],
            "how_to_export": "TODO: how an agent ingests this source on demand.",
        }
    }
    dumped = yaml.safe_dump(recipe, sort_keys=False, allow_unicode=True).rstrip("\n")
    return (
        "## Recipe\n\n"
        "<!-- Assisted-migration scaffold — complete the TODOs and remove this note. -->\n\n"
        f"```yaml\n{dumped}\n```\n"
    )


def _plan_source_page(
    root: Path, rel: str, values: dict[str, Any], today: dt.date
) -> SourceMigrationChange:
    config_values = _config_page_values(root, values)
    additions: dict[str, Any] = {}
    notes: list[str] = []

    if not str(values.get("platform") or "").strip():
        platform, guessed = infer_platform(values)
        additions["platform"] = platform
        if guessed:
            notes.append(f"platform guessed as `{platform}` — confirm")
    else:
        platform = str(values.get("platform")).strip()

    if not str(values.get("source_locator") or "").strip():
        locator, is_todo = infer_locator(rel, values, platform)
        additions["source_locator"] = locator
        if is_todo:
            notes.append("source_locator is a TODO placeholder — set the real id")

    if not str(values.get("owner") or "").strip():
        owner = infer_owner(values, config_values)
        if owner:
            additions["owner"] = owner
        else:
            notes.append("owner could not be inferred — set it manually")

    # Only add `sync` when the key is genuinely ABSENT. A present-but-scalar/list
    # sync is left alone (adding would duplicate the YAML key and clobber it) and
    # noted for the reviewer instead.
    if "sync" not in values:
        additions["sync"] = {"last_run_at": "", "last_status": "never", "last_event_ref": ""}
    elif not isinstance(values.get("sync"), dict):
        notes.append("`sync` exists but is not a mapping — fix it by hand")

    return SourceMigrationChange(
        rel=rel, page_type="source", add_frontmatter=additions, notes=tuple(notes)
    )


def _plan_source_config_page(
    root: Path,
    rel: str,
    values: dict[str, Any],
    text: str,
    linked_source: dict[str, Any] | None = None,
) -> SourceMigrationChange:
    if extract_recipe_mapping(text) is not None:
        return SourceMigrationChange(rel=rel, page_type="source_config")
    # Inherit platform/locator from the source page this config governs, so the
    # recipe matches the entity instead of guessing from the thin config page.
    source = linked_source or {}
    platform, guessed = infer_platform({**source, **values})
    locator, is_todo = infer_locator(
        source.get("_rel", rel), {**source, **values}, platform
    )
    notes: list[str] = ["scaffolded a TODO recipe — complete the streams + export steps"]
    if guessed:
        notes.append(f"recipe platform guessed as `{platform}` — confirm")
    if is_todo:
        notes.append("recipe locator is a TODO placeholder — set the real id")
    return SourceMigrationChange(
        rel=rel,
        page_type="source_config",
        append_recipe=scaffold_recipe_block(platform, locator),
        notes=tuple(notes),
    )


def plan_source_migration(
    root: Path, config: WikiConfig, today: dt.date | None = None
) -> list[SourceMigrationChange]:
    """Scan ``memories/`` and return the additive changes needed to bring every
    source / source_config page up to contract. Empty changes are dropped."""
    today = today or dt.date.today()
    memory_root = root / str(config.paths.get("memory_root") or "memories")
    if not memory_root.exists():
        return []
    md_paths = sorted(memory_root.rglob("*.md"))

    # Index source pages by page_id so a source_config can inherit its entity's
    # platform/locator instead of guessing from the thin config page.
    source_by_id: dict[str, dict[str, Any]] = {}
    for path in md_paths:
        values = parse_frontmatter(path)[0]
        if str(values.get("page_type") or "") == "source":
            page_id = str(values.get("page_id") or "").strip()
            if page_id:
                source_by_id[page_id] = {**values, "_rel": path.relative_to(root).as_posix()}

    changes: list[SourceMigrationChange] = []
    for path in md_paths:
        values = parse_frontmatter(path)[0]
        page_type = str(values.get("page_type") or "")
        rel = path.relative_to(root).as_posix()
        if page_type == "source":
            change = _plan_source_page(root, rel, values, today)
        elif page_type == "source_config":
            refs = values.get("source_refs")
            linked = None
            for ref in refs if isinstance(refs, list) else []:
                if str(ref) in source_by_id:
                    linked = source_by_id[str(ref)]
                    break
            change = _plan_source_config_page(
                root, rel, values, path.read_text(encoding="utf-8"), linked
            )
        else:
            continue
        if not change.is_empty():
            changes.append(change)
    return changes


def insert_frontmatter_keys(text: str, additions: dict[str, Any]) -> str:
    """Append keys to the frontmatter block, just before its closing ``---``,
    preserving the existing field order and body verbatim. Creates a frontmatter
    block if the page has none. Keys ALREADY present are dropped, never appended,
    so we can't produce a duplicate YAML key that silently clobbers a value."""
    if not additions:
        return text
    match = FRONTMATTER_RE.match(text)
    if not match:
        dumped = yaml.safe_dump(additions, sort_keys=False, allow_unicode=True).rstrip("\n")
        return f"---\n{dumped}\n---\n\n{text}"
    inner = match.group(1)
    try:
        existing = yaml.safe_load(inner)
    except yaml.YAMLError:
        existing = None
    present = set(existing) if isinstance(existing, dict) else set()
    fresh = {k: v for k, v in additions.items() if k not in present}
    if not fresh:
        return text
    dumped = yaml.safe_dump(fresh, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{inner.rstrip(chr(10))}\n{dumped}\n---\n" + text[match.end() :]


def apply_change(root: Path, change: SourceMigrationChange) -> None:
    """Write one change to disk (additive frontmatter, then appended recipe)."""
    path = root / change.rel
    text = path.read_text(encoding="utf-8")
    if change.add_frontmatter:
        text = insert_frontmatter_keys(text, change.add_frontmatter)
    if change.append_recipe:
        separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        text = f"{text}{separator}{change.append_recipe}"
    path.write_text(text, encoding="utf-8")
