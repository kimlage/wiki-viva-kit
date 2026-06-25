#!/usr/bin/env python3
"""Audit the local Markdown/Git wiki contract."""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config
from wiki_core.detectors import scan_file
from wiki_core.frontmatter import parse_frontmatter as canonical_parse_frontmatter
from wiki_core.frontmatter import parse_frontmatter_flat_with_errors
from wiki_core.gate import STATES as GATE_STATES
from wiki_core.graph import build_page_graph, compute_impact, min_outbound_violations, orphan_pages, unreachable_pages
from wiki_core.page_types import (
    PAGE_TYPES_SCHEMA_VERSION,
    load_page_type_registry,
    template_coverage_error,
    validate_shape,
)
from wiki_core.paths import WikiPaths

REQUIRED_KEYS = {
    "page_id",
    "page_type",
    "context",
    "visibility",
    "updated_at",
    "stale_after_days",
    "sources_policy",
    "gate",
    "sensitive_data_policy",
}

RELATION_KEYS = {
    "owner",
    "related_holons",
    "roles",
    "responsibilities",
    "source_refs",
    "claims",
    "decisions",
    "actions",
    "evidence_refs",
}

def memory_prefix(config: WikiConfig) -> str:
    """Repo-relative memory root with a trailing slash (prefix-match shape)."""
    return str(config.paths["memory_root"]).rstrip("/") + "/"


def wiki_paths(config: WikiConfig) -> WikiPaths:
    """WikiPaths bound to the CURRENT module ROOT (tests monkeypatch ROOT)."""
    return WikiPaths(ROOT, config)


def primary_pages(config: WikiConfig) -> list[str]:
    """Required pages: method core (audit.core_pages in the config) + one hub
    per declared context, both rooted at the configured memory_root."""
    root = memory_prefix(config)
    core = [str(page) for page in (config.audit.get("core_pages") or ())]
    return core + [f"{root}{ctx}/index.md" for ctx in config.contexts]


# Page-type vocabulary per ontology directory, keyed by the DIRNAME directly
# under the memory root. The dirnames are a SUPERSET of the English defaults and
# the Portuguese names: compatibility so one shared codebase serves localized
# (pt) repo layouts. The page_type values themselves are FROZEN vocabulary
# (persisted in page frontmatter) and must not be renamed.
_ONTOLOGY_DIRNAME_GROUPS: dict[tuple[str, ...], set[str]] = {
    ("ontology", "ontologia"): {"ontology_index", "operational_rule"},
    ("people", "pessoas"): {"ontology_index", "person", "profile"},
    ("holons",): {"ontology_index", "holon"},
    ("roles", "papeis"): {"ontology_index", "role"},
    ("responsibilities", "responsabilidades"): {"ontology_index", "responsibility"},
    ("assignments", "atribuicoes"): {"ontology_index", "assignment"},
    ("projects", "projetos"): {"ontology_index", "project"},
    ("initiatives", "iniciativas"): {"ontology_index", "initiative"},
    ("sources", "fontes"): {"ontology_index", "source", "source_catalog", "artifact", "source_registry", "source_config"},
    ("claims",): {"ontology_index", "claim"},
    ("decisions", "decisoes"): {"ontology_index", "decision"},
    ("insights",): {"ontology_index", "insight"},
    ("actions", "acoes"): {"ontology_index", "action"},
    ("timelines",): {"ontology_index", "timeline"},
    ("evidence", "evidencias"): {"ontology_index", "evidence"},
    ("coverage", "cobertura"): {"ontology_index", "coverage"},
    # External-tool entities (Phase 2): meetings, cards (Jira/tickets) and
    # calendar events, linked to people/decisions/actions/source. Live connectors
    # stay the agent's job; the toolkit only models and audits the entities.
    ("meetings", "reunioes"): {"ontology_index", "meeting"},
    ("cards", "cartoes"): {"ontology_index", "external_card"},
    ("calendar", "calendario"): {"ontology_index", "calendar_event"},
}

ONTOLOGY_DIRNAME_TYPES: dict[str, set[str]] = {
    name: types for names, types in _ONTOLOGY_DIRNAME_GROUPS.items() for name in names
}


def ontology_dir_for(rel: str, config: WikiConfig) -> str | None:
    """Ontology directory (repo-relative) containing `rel`, or None."""
    prefix = memory_prefix(config)
    if not rel.startswith(prefix):
        return None
    head, _, tail = rel[len(prefix):].partition("/")
    if not tail:
        return None  # file directly under the memory root, not in an ontology dir
    if head in ONTOLOGY_DIRNAME_TYPES:
        return prefix + head
    return None


# Generated-id prefixes accepted per relation key. SUPERSET of the English and
# Portuguese prefixes: compatibility so one shared codebase validates localized
# (pt) repos, whose pages already persist pt-generated ids.
RELATION_PREFIXES = {
    "owner": ("person-", "pessoa-", "role-", "papel-", "holon-", "root-"),
    "related_holons": ("holon-",),
    "roles": ("role-", "papel-"),
    "responsibilities": ("responsibility-", "responsabilidade-"),
    "source_refs": ("source-", "sources-", "fonte-", "evidence-", "evidencia-"),
    "claims": ("claim-",),
    "decisions": ("decision-", "decisao-"),
    "actions": ("action-", "acao-"),
}

LINK_AUDIT_FILES = {
    ".github/pull_request_template.md",
    "AGENTS.md",
}


def _top_level_roots(config: WikiConfig) -> list[str]:
    """Sorted unique FIRST path segments of the configured layout roots, plus
    the fixed repo dirs (scripts/, .github/) every kit repo carries."""
    segments = {
        str(config.paths[key]).split("/", 1)[0]
        for key in ("memory_root", "references_root", "raw_root", "derived_root", "skills_root")
    }
    segments.update({"scripts", ".github"})
    return sorted(segments)


def _compile_local_path_regexes(
    config: WikiConfig,
) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    roots = "|".join(re.escape(segment) for segment in _top_level_roots(config))
    prefix_re = re.compile(rf"^(?:AGENTS\.md|(?:{roots})(?:/|$))")
    inline_code_re = re.compile(rf"`((?:AGENTS\.md|{roots})(?:/|\b)[^`\n]*)`")
    bare_re = re.compile(
        r"(?<![A-Za-z0-9_./-])"
        rf"(AGENTS\.md|(?:{roots})/[A-Za-z0-9_./*%-]+)"
    )
    return prefix_re, inline_code_re, bare_re


def build_local_path_regexes(config: WikiConfig) -> None:
    """(Re)build the module-level local-path regexes from the configured roots.

    Kept module-level so the hot loops reuse compiled patterns; main() calls
    this with the loaded config, and tests call it with a fixture config.
    """
    global LOCAL_PATH_PREFIX_RE, INLINE_CODE_LOCAL_PATH_RE, BARE_LOCAL_PATH_RE
    LOCAL_PATH_PREFIX_RE, INLINE_CODE_LOCAL_PATH_RE, BARE_LOCAL_PATH_RE = (
        _compile_local_path_regexes(config)
    )


# Bind the regexes to this repo's layout at import; main() rebinds explicitly.
build_local_path_regexes(load_config(ROOT))

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_LINK_LABEL_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Fixed: stops at the first space/boundary (the old version swallowed the
# following prose with the space inside the character class, making the check inert).
ABSOLUTE_USER_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+/[^\s)\]]+")
# A traversal disguised as relative that climbs up to the author's home (e.g. ../../../../Downloads/...).
HOME_TRAVERSAL_RE = re.compile(r"(?:\.\./){2,}[^\s)\]]*Downloads[^\s)\]]*")
IMPACT_METADATA_FRONTMATTER_RE = re.compile(
    r"^\s*(updated_at|last_updated|date_modified|modified_at|last_ingested_at|"
    r"source_type|ingestion_state|refresh_policy|refresh_cadence_days|"
    r"next_refresh_at|refresh_trigger|refresh_priority):\s*.+$",
    re.IGNORECASE,
)
IMPACT_METADATA_BODY_RE = re.compile(
    r"^\s*(Atualizado em|Last updated|Updated at):\s*.+$",
    re.IGNORECASE,
)

TEXT_SCAN_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".csv", ".toml", ".ini", ".cfg", ".sh"}
# Files that legitimately contain example secret patterns (fixtures, detector).
SECRET_SCAN_SKIP_PREFIXES = ("tests/", "wiki_core/detectors/")
PUBLIC_VISIBILITIES = {"public", "public_candidate"}
PROMOTION_REQUIRED_FIELDS = (
    "consent_by",
    "promoted_fields",
    "source_visibility",
    "anonymized",
    "approved_gate",
    "revert_plan",
)
# Placeholder phrases from the ingestion generator (multi-word to avoid matching
# substrings of real prose). Includes pt and en to support both languages.
QUADRANT_PLACEHOLDERS = (
    "a preencher", "explicitar se ausente", "preencher apos leitura",
    "to fill in", "state if absent", "fill in after",
)
# Accepted markers for the quadrants section (pt or en).
QUADRANTS_HEADERS = ("## Quadrantes", "## Quadrants")
# Caches deliberately unversioned (gitignored): links/evidence_refs pointing to
# them reference a local cache or the original on Drive and are not required in
# the repo (otherwise the auditor would fail on a clean clone/CI).
GITIGNORED_LINK_PREFIXES = ("data/raw", "data/derived")

# Entity mention -> link (warn). Pages of these types (and any page in an ontology
# dir) are "linkable entities": when their title/alias is named in another page's
# prose without a link, the auditor WARNS (never blocks) so the wiki stays
# connected. Conservative to avoid noise: minimum alias length + a common-word
# denylist; matches outside code/links only; one warning per page.
ENTITY_PAGE_TYPES = {
    "person", "source", "decision", "holon", "role", "responsibility",
    "project", "initiative", "claim", "insight", "action", "timeline",
    "evidence", "assignment", "meeting", "external_card", "calendar_event",
}
ENTITY_CANONICAL_NAME_PAGE_TYPES = ENTITY_PAGE_TYPES - {
    "action", "timeline", "evidence", "assignment",
}
# Generated source events and append-only logs may intentionally preserve raw or
# historical wording. Requiring retroactive link edits there creates audit noise
# and can weaken provenance; canonical pages remain covered by mention links.
MENTION_LINK_EXEMPT_PAGE_TYPES = {"ingestion_event", "system_log"}
MENTION_MIN_ALIAS_LEN = 4
MENTION_COMMON_WORDS = {
    "index", "source", "memory", "memoria", "memorias", "note", "page", "pages",
    "status", "gate", "owner", "system", "sistema", "context", "contexto",
}
ENTITY_TITLE_PREFIX_RE = re.compile(
    r"^(?:pessoa|person|fonte|source|projeto|project|claim|decisao|decision)\s*-\s*",
    re.IGNORECASE,
)

# Strict local mode (--strict-local): requires links to derived/raw artifacts
# (gitignored) to actually exist on disk. Default False for clean clone/CI.
STRICT_LOCAL = False

# --list-stale-gaps: lists each memory page without declared freshness (instead
# of just the total). The check itself does not fail (warning) until the owner
# triages the windows.
LIST_STALE_GAPS = False


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def changed_paths_for_audit() -> set[str]:
    """Current diff against the likely PR base plus working tree changes."""
    changed: set[str] = set()
    for base in ("origin/main", "main"):
        if run_git(["rev-parse", "--verify", "--quiet", base]):
            changed.update(run_git(["diff", "--name-only", f"{base}...HEAD"]).splitlines())
            break
    changed.update(run_git(["diff", "--name-only"]).splitlines())
    changed.update(run_git(["diff", "--cached", "--name-only"]).splitlines())
    return {path for path in changed if path}


@functools.lru_cache(maxsize=1)
def _audit_base_ref() -> str | None:
    for base in ("origin/main", "main"):
        if run_git(["rev-parse", "--verify", "--quiet", base]):
            return base
    return None


@functools.lru_cache(maxsize=None)
def _text_at_audit_base(rel: str) -> str | None:
    base = _audit_base_ref()
    if not base:
        return None
    if rel not in run_git(["ls-tree", "-r", "--name-only", base, "--", rel]).splitlines():
        return None
    return run_git(["show", f"{base}:{rel}"])


def _semantic_impact_text(text: str) -> str:
    """Text used by impact propagation.

    Impact review is about downstream meaning. Link retargeting, date stamps and
    markdown reflow are validated elsewhere, so they should not force every
    backlink to be re-reviewed.
    """
    normalized: list[str] = []
    in_frontmatter = False
    for index, line in enumerate(text.splitlines()):
        if index == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter and line.strip() == "---":
            in_frontmatter = False
            continue
        if in_frontmatter and IMPACT_METADATA_FRONTMATTER_RE.match(line):
            continue
        if IMPACT_METADATA_BODY_RE.match(line):
            continue
        normalized.append(MARKDOWN_LINK_LABEL_RE.sub(lambda match: match.group(1), line))
    return re.sub(r"\s+", " ", "\n".join(normalized)).strip()


def _link_or_metadata_only_change(rel: str) -> bool:
    if not rel.endswith(".md"):
        return False
    current = ROOT / rel
    if not current.exists():
        return False
    previous = _text_at_audit_base(rel)
    if previous is None:
        return False
    return _semantic_impact_text(previous) == _semantic_impact_text(
        current.read_text(encoding="utf-8", errors="replace")
    )


def _impact_relevant_changed_paths() -> set[str]:
    return {
        rel
        for rel in changed_paths_for_audit()
        if not _link_or_metadata_only_change(rel)
    }


@functools.lru_cache(maxsize=1)
def tracked_files() -> list[str]:
    # Memoized: it was called ~8x per run (each audit_* via markdown_files),
    # running 2 git subprocesses per call — ~16 git forks per audit.
    # The file set does not change during a run; main() clears the cache.
    tracked = run_git(["ls-files"])
    untracked = run_git(["ls-files", "--others", "--exclude-standard"])
    candidates = {line for output in (tracked, untracked) for line in output.splitlines() if line}
    return sorted(rel for rel in candidates if (ROOT / rel).exists())


def markdown_files() -> list[str]:
    return [rel for rel in tracked_files() if rel.endswith(".md")]


def link_audit_files(config: WikiConfig) -> list[str]:
    paths = wiki_paths(config)
    prefixes = (
        memory_prefix(config),
        paths.rel(paths.templates_root) + "/",
        paths.rel(paths.skills_root) + "/",
    )
    files = []
    for rel in markdown_files():
        if rel.startswith(prefixes) or rel in LINK_AUDIT_FILES:
            files.append(rel)
    return sorted(files)


@functools.lru_cache(maxsize=None)
def parse_frontmatter(path: Path) -> tuple[dict[str, object], list[str]]:
    # Memoized per path: several audit_* checks re-parse the same pages within a
    # single run (frontmatter, stale coverage, relations, PII, promotion...).
    # The file set does not change during a run; main() clears the cache.
    #
    # Delegates to the canonical flat parser (string-flattening is LOAD-BEARING
    # for the shape gate); REQUIRED_KEYS is enforced here as the audit contract.
    return parse_frontmatter_flat_with_errors(path, required_keys=REQUIRED_KEYS)


def parse_yaml_frontmatter(path: Path) -> dict[str, object]:
    # Structured (yaml) read for nested maps the flat parser can't represent
    # (affected_pages.must_update, impact_closure).
    values, _body = canonical_parse_frontmatter(path)
    return values


def list_values(values: dict[str, object], key: str) -> list[str]:
    # Audit-local: takes (values, key) and does NOT strip items (the audit gate
    # compares raw frontmatter text). Distinct from the canonical
    # wiki_core.frontmatter.list_values, which strips and takes a bare value.
    value = values.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str):
        if value == "[]":
            return []
        return [value]
    return []


def body_lines_without_frontmatter(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    start = 0
    if lines and lines[0] == "---":
        try:
            start = lines[1:].index("---") + 2
        except ValueError:
            start = 0
    body = []
    in_fence = False
    for offset, line in enumerate(lines[start:], start + 1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            body.append((offset, line))
    return body


def is_external_link(href: str) -> bool:
    parsed = urlparse(href)
    return bool(parsed.scheme) or href.startswith("#")


def local_link_target_path(source_rel: str, href: str) -> Path | None:
    href = href.split("#", 1)[0]
    if not href:
        return None
    if is_external_link(href):
        return None
    href = unquote(href)
    if href.startswith("/"):
        target = ROOT / href.lstrip("/")
    else:
        target = (ROOT / source_rel).parent / href
    try:
        rel = target.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        # Link points outside the repo (e.g. ~/Downloads): it is not a versioned
        # artifact, so the auditor does not validate its existence. (The non-
        # portability of these links is handled in separate content cleanup.)
        return None
    if rel.startswith(GITIGNORED_LINK_PREFIXES):
        # By default we tolerate links to derived/raw artifacts (gitignored): a
        # clean clone/CI does not have them. In --strict-local we require them to
        # actually exist on disk (catches a dangling derived reference in a real env).
        return target if STRICT_LOCAL else None
    return target


def local_link_target_exists(source_rel: str, href: str) -> bool:
    target = local_link_target_path(source_rel, href)
    if target is None:
        return True
    return target.exists()


def local_link_target_is_directory(source_rel: str, href: str) -> bool:
    target = local_link_target_path(source_rel, href)
    return bool(target and target.exists() and target.is_dir())


def bare_local_path_exists(value: str) -> bool:
    if value == "AGENTS.md":
        return (ROOT / value).exists()
    if "*" in value:
        value = value.split("*", 1)[0]
    return (ROOT / value.rstrip("/")).exists()


def local_paths_in_text(value: str) -> list[str]:
    paths: list[str] = []
    for match in BARE_LOCAL_PATH_RE.finditer(value):
        candidate = match.group(1)
        if bare_local_path_exists(candidate):
            paths.append(candidate)
    return paths


def line_has_link_for_path(line: str, value: str) -> bool:
    basename = value.rsplit("/", 1)[-1]
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", line):
        label = match.group(1)
        href = unquote(match.group(2))
        if value in label or value in href:
            return True
        # A Drive link satisfies when the label carries the file NAME
        # (general rule: unversioned artifact points to Drive).
        if basename and basename in label and "drive.google.com" in href:
            return True
    return False


def page_catalog(errors: list[str], config: WikiConfig) -> dict[str, tuple[str, dict[str, object]]]:
    prefix = memory_prefix(config)
    catalog: dict[str, tuple[str, dict[str, object]]] = {}
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        values, _ = parse_frontmatter(ROOT / rel)
        page_id = values.get("page_id")
        if not isinstance(page_id, str) or not page_id:
            continue
        if page_id in catalog:
            errors.append(f"{rel}: duplicate page_id `{page_id}` also in {catalog[page_id][0]}")
        catalog[page_id] = (rel, values)
    return catalog


def audit_frontmatter(errors: list[str], warnings: list[str], config: WikiConfig) -> None:
    today = dt.date.today()
    pages = set(primary_pages(config))
    pages.update(rel for rel in markdown_files() if ontology_dir_for(rel, config))
    for rel in sorted(pages):
        path = ROOT / rel
        if not path.exists():
            errors.append(f"{rel}: missing primary page")
            continue
        values, page_errors = parse_frontmatter(path)
        for error in page_errors:
            errors.append(f"{rel}: {error}")
        if not values:
            continue

        try:
            updated_at = dt.date.fromisoformat(str(values["updated_at"]))
            stale_after = int(str(values["stale_after_days"]))
        except (KeyError, ValueError):
            errors.append(f"{rel}: invalid updated_at or stale_after_days")
            continue
        if updated_at + dt.timedelta(days=stale_after) < today:
            warnings.append(f"{rel}: stale page")

        directory = ontology_dir_for(rel, config)
        if directory:
            missing_relations = sorted(RELATION_KEYS - values.keys())
            if missing_relations:
                errors.append(f"{rel}: missing relation keys: {', '.join(missing_relations)}")
            page_type = str(values.get("page_type", ""))
            allowed = ONTOLOGY_DIRNAME_TYPES[directory.rsplit("/", 1)[-1]]
            if page_type not in allowed:
                errors.append(f"{rel}: page_type `{page_type}` not allowed in {directory}")


# Extension relaxed to [A-Za-z0-9]{1,8}: the old [a-z]{2,4} missed .jsonl,
# .sqlite and other longer/mixed-case extensions, letting unversioned-artifact
# links escape the audit.
LOCAL_ARTIFACT_LINK_RE = re.compile(
    r"\]\((?:\.\./)+data/(?:raw|derived)/[^)]*\.[A-Za-z0-9]{1,8}\)"
)


def audit_freshness_budget(errors: list[str], warnings: list[str], config: WikiConfig) -> None:
    """Freshness budget with a gate that BITES (P1 of the critical review).

    Isolated staleness is a warning; but when the total of stale pages exceeds the
    budget (`audit.freshness_budget` in the config), it becomes an ERROR — it forces
    triage before the freshness debt piles up beyond what the owner can review.
    The daily cron (manual addition) reuses this same gate.
    """
    try:
        budget = int(str(config.audit.get("freshness_budget", 0) or 0))
    except (TypeError, ValueError):
        errors.append("config: audit.freshness_budget invalid (integer expected)")
        return
    if budget <= 0:
        return
    stale = sum(1 for w in warnings if w.endswith(": stale page"))
    if stale > budget:
        errors.append(
            f"freshness budget exceeded: {stale} stale page(s) > budget {budget} "
            "(triage/update pages or adjust stale_after_days/audit.freshness_budget)"
        )


def audit_command_reference(errors: list[str], config: WikiConfig) -> None:
    """Doc-code gate of the meta-wiki (P2): the command reference must not drift.

    Every tracked `scripts/wiki_*.py` CLI must be cited in the configured
    command-reference page, and every `wiki_*.py` cited there must exist in the
    repo. Cheap to maintain (one row in the table) and kills silent doc-code drift.
    """
    ref_rel = str(config.paths["command_reference_page"])
    ref_path = ROOT / ref_rel
    tracked_clis = {
        Path(rel).name
        for rel in tracked_files()
        if rel.startswith("scripts/wiki_") and rel.endswith(".py")
    }
    if not ref_path.exists():
        # FAIL LOUD: with wiki CLIs tracked, a missing reference page means the
        # doc-code gate cannot run at all (it used to no-op silently). With no
        # wiki CLIs tracked the gate is inapplicable and stays quiet.
        if tracked_clis:
            errors.append(
                f"{ref_rel}: missing command reference page "
                f"({len(tracked_clis)} tracked wiki CLI(s) to document)"
            )
        return
    text = ref_path.read_text(encoding="utf-8")
    mentioned = set(re.findall(r"\b(wiki_[a-z0-9_]+\.py)\b", text))
    for name in sorted(tracked_clis - mentioned):
        errors.append(f"{ref_rel}: undocumented CLI: {name}")
    for name in sorted(mentioned - tracked_clis):
        errors.append(f"{ref_rel}: documented but nonexistent CLI: {name}")


def audit_drive_artifact_links(warnings: list[str], config: WikiConfig) -> None:
    """General rule: the wiki must not link to an unversioned local FILE.

    A link to a file under data/raw/** or data/derived/** (gitignored) breaks on
    GitHub. The content should live in the personal Drive folder (id in .env) via
    `scripts/wiki_drive_publish.py`, and the page should point to the view_url of
    the versioned manifest data/drive_artifacts_manifest.json. Links to VERSIONED
    files inside data/ (e.g. manifest, versioned rules) are ok.
    Aggregated warning (extensive historical legacy); the list comes out with --list-stale-gaps.
    """
    tracked = set(tracked_files())
    prefix = memory_prefix(config)
    offenders: dict[str, int] = {}
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        count = 0
        for match in LOCAL_ARTIFACT_LINK_RE.finditer(text):
            target = re.sub(r"^\]\(", "", match.group(0)).rstrip(")")
            normalized = re.sub(r"^(\.\./)+", "", target)
            normalized = normalized.replace("%20", " ").replace("%28", "(").replace("%29", ")")
            if normalized in tracked:
                continue  # versioned file: local link works on GitHub
            count += 1
        if count:
            offenders[rel] = count
    if not offenders:
        return
    total = sum(offenders.values())
    if LIST_STALE_GAPS:
        for rel, count in sorted(offenders.items()):
            warnings.append(
                f"{rel}: {count} local link(s) to unversioned artifact; "
                "publish on Drive (wiki_drive_publish) and point to the view_url"
            )
    else:
        warnings.append(
            f"{total} link(s) to unversioned local artifact in {len(offenders)} page(s); "
            "general rule: content on Drive (wiki_drive_publish) and the wiki points to the "
            "manifest view_url. Use --list-stale-gaps to list."
        )


def audit_stale_coverage(warnings: list[str], config: WikiConfig) -> None:
    """Freshness coverage for ALL memory pages.

    `audit_frontmatter` only evaluates freshness on primary_pages + ontology; ~36% of
    pages had `stale_after_days` but were never checked (an old page outside that
    set never warned). Here we evaluate the freshness of every memory page that has
    the field, and list those without `stale_after_days` nor `stale_exempt: true`.
    Does not fail (warning) — explicit per-page opt-out.
    """
    prefix = memory_prefix(config)
    today = dt.date.today()
    already = set(primary_pages(config))
    already.update(rel for rel in markdown_files() if ontology_dir_for(rel, config))
    gaps: list[str] = []
    for rel in markdown_files():
        if not rel.startswith(prefix) or rel in already:
            continue
        values, _ = parse_frontmatter(ROOT / rel)
        if not values:
            continue
        exempt = str(values.get("stale_exempt", "")).strip().lower() in {"true", "yes", "on", "1"}
        if "stale_after_days" not in values:
            if not exempt:
                gaps.append(rel)
            continue
        if exempt:
            continue
        try:
            updated_at = dt.date.fromisoformat(str(values["updated_at"]))
            stale_after = int(str(values["stale_after_days"]))
        except (KeyError, ValueError):
            warnings.append(f"{rel}: invalid updated_at or stale_after_days")
            continue
        if updated_at + dt.timedelta(days=stale_after) < today:
            warnings.append(f"{rel}: stale page")
    if not gaps:
        return
    if LIST_STALE_GAPS:
        for rel in sorted(gaps):
            warnings.append(f"{rel}: no declared freshness (stale_after_days) nor stale_exempt")
    else:
        warnings.append(
            f"{len(gaps)} memory page(s) with no declared freshness "
            "(stale_after_days) nor stale_exempt; run --list-stale-gaps to list"
        )


def audit_relations(errors: list[str], config: WikiConfig) -> None:
    catalog = page_catalog(errors, config)
    page_ids = set(catalog)
    for rel in markdown_files():
        if not ontology_dir_for(rel, config):
            continue
        values, _ = parse_frontmatter(ROOT / rel)
        for key, prefixes in RELATION_PREFIXES.items():
            for target in list_values(values, key):
                if target not in page_ids:
                    errors.append(f"{rel}: {key} references missing page_id `{target}`")
                elif prefixes and not target.startswith(prefixes):
                    errors.append(f"{rel}: {key} target `{target}` has unexpected prefix")
        for target in list_values(values, "evidence_refs"):
            if target.startswith(("http://", "https://", "/")):
                continue  # URL or external/machine absolute path (unversioned)
            if target.startswith(GITIGNORED_LINK_PREFIXES):
                continue  # unversioned cache (data/raw, data/derived)
            if not (ROOT / target).exists():
                errors.append(f"{rel}: evidence_refs path does not exist: `{target}`")

        # Claim conflict/supersede vocabulary (consolidation): optional fields,
        # but when present they must point at real claim pages — and supersede
        # must be reciprocal so the graph of versions stays honest.
        for key in ("supersedes", "conflicts_with"):
            for target in list_values(values, key):
                if target not in page_ids:
                    errors.append(f"{rel}: {key} references missing page_id `{target}`")
                elif not target.startswith("claim-"):
                    errors.append(f"{rel}: {key} target `{target}` has unexpected prefix")
        superseded_by = str(values.get("superseded_by") or "").strip()
        if superseded_by:
            if superseded_by not in page_ids:
                errors.append(f"{rel}: superseded_by references missing page_id `{superseded_by}`")
            elif not superseded_by.startswith("claim-"):
                errors.append(f"{rel}: superseded_by target `{superseded_by}` has unexpected prefix")
        this_id = str(values.get("page_id") or "")
        for target in list_values(values, "supersedes"):
            if target in catalog:
                other_rel, other_values = catalog[target]
                other_back = str(other_values.get("superseded_by") or "").strip()
                if other_back and other_back != this_id:
                    errors.append(
                        f"{rel}: supersedes `{target}` but {other_rel} declares "
                        f"superseded_by `{other_back}` (non-reciprocal supersede)"
                    )


# Retired pre-wiki layout of this project family: a denylist, not a layout key.
# `docs/memories/` is the English twin of `docs/memorias/` — superset so one
# shared codebase guards localized (pt) repos and the English defaults alike.
LEGACY_DOCS_PREFIXES = ("docs/2026/", "docs/memorias/", "docs/memories/")
LEGACY_DOCS_MARKERS = ("docs/2026", "docs/memorias", "docs/memories")


def audit_old_paths(errors: list[str], config: WikiConfig) -> None:
    allowed = {str(rel) for rel in (config.audit.get("allowed_old_path_references") or ())}
    for rel in tracked_files():
        if rel.startswith(LEGACY_DOCS_PREFIXES):
            errors.append(f"{rel}: old docs path is still tracked")
        if not rel.endswith(".md"):
            continue
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(marker in text for marker in LEGACY_DOCS_MARKERS) and rel not in allowed:
            errors.append(f"{rel}: old docs path reference outside migration history")


def _scannable_text_files() -> list[str]:
    files = []
    for rel in tracked_files():
        if rel.startswith(SECRET_SCAN_SKIP_PREFIXES):
            continue
        if Path(rel).suffix.lower() in TEXT_SCAN_SUFFIXES:
            files.append(rel)
    return files


def audit_secrets(errors: list[str], config: WikiConfig) -> None:
    """Credentials/secrets can never be versioned (absolute block, any file)."""
    if not config.audit.get("forbid_access_secrets", True):
        return
    for rel in _scannable_text_files():
        for finding in scan_file(ROOT / rel):
            if finding.category == "secret":
                errors.append(f"{rel}:{finding.line}: possible {finding.kind} secret ({finding.excerpt})")


def audit_pii(errors: list[str], warnings: list[str], config: WikiConfig, public_export: bool = False) -> None:
    """Personal data (PII) is WELCOME in private pages of this personal repo:
    it produces neither error nor warning -- storing CPF/CNPJ, amounts, counterparties
    and dates is the very purpose of operational memory. PII only becomes an error at the
    PUBLIC BOUNDARY: public/public_candidate page or export (`--public-export`). Access
    secrets are handled separately (audit_secrets), with an absolute block everywhere."""
    prefix = memory_prefix(config)
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        values, _ = parse_frontmatter(ROOT / rel)
        visibility = str(values.get("visibility", config.default_visibility))
        pii = [f for f in scan_file(ROOT / rel) if f.category == "pii"]
        if not pii:
            continue
        if public_export or visibility in PUBLIC_VISIBILITIES:
            for finding in pii:
                errors.append(f"{rel}:{finding.line}: PII in {visibility} page: {finding.kind} ({finding.excerpt})")
        elif not config.private_sensitive_allowed:
            # Optional strict mode (opt-in): only when the owner disables PII in private.
            for finding in pii:
                errors.append(f"{rel}:{finding.line}: PII with private_sensitive_allowed=false: {finding.kind} ({finding.excerpt})")
        # Default case (private_sensitive_allowed=true): PII in a private page is
        # expected in personal operational memory -- silent, no error nor warning.


def audit_clickable_local_links(errors: list[str], config: WikiConfig) -> None:
    for rel in link_audit_files(config):
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in body_lines_without_frontmatter(text):
            for match in MARKDOWN_LINK_RE.finditer(line):
                href = match.group(1)
                if not local_link_target_exists(rel, href):
                    errors.append(f"{rel}:{lineno}: markdown link target does not exist: `{href}`")

            for match in INLINE_CODE_LOCAL_PATH_RE.finditer(line):
                value = match.group(1)
                if LOCAL_PATH_PREFIX_RE.match(value):
                    errors.append(
                        f"{rel}:{lineno}: local path must be a markdown link, not inline code: `{value}`"
                    )

            for match in INLINE_CODE_RE.finditer(line):
                code = match.group(0).strip("`")
                for value in local_paths_in_text(code):
                    if not line_has_link_for_path(line, value):
                        errors.append(
                            f"{rel}:{lineno}: command mentions local path without same-line link: `{value}`"
                        )

            without_links = MARKDOWN_LINK_RE.sub("", line)
            without_links_or_code = INLINE_CODE_RE.sub("", without_links)
            for match in BARE_LOCAL_PATH_RE.finditer(without_links_or_code):
                value = match.group(1)
                if bare_local_path_exists(value):
                    errors.append(
                        f"{rel}:{lineno}: local path must be a markdown link: `{value}`"
                    )


def audit_obsidian_directory_links(warnings: list[str], config: WikiConfig) -> None:
    """Warn on Markdown links that point to directories.

    GitHub can render a directory target, but Obsidian treats many of these as a
    note creation request. The portable pattern is to link a concrete index file
    such as README.md or index.md.
    """
    offenders: dict[str, int] = {}
    for rel in link_audit_files(config):
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        count = 0
        for _lineno, line in body_lines_without_frontmatter(text):
            for match in MARKDOWN_LINK_RE.finditer(line):
                if local_link_target_is_directory(rel, match.group(1)):
                    count += 1
        if count:
            offenders[rel] = count
    if not offenders:
        return
    total = sum(offenders.values())
    if LIST_STALE_GAPS:
        for rel, count in sorted(offenders.items()):
            warnings.append(
                f"{rel}: {count} markdown link(s) point to directories; "
                "link an index file for Obsidian navigation"
            )
    else:
        warnings.append(
            f"{total} markdown link(s) point to directories in {len(offenders)} file(s); "
            "link README.md/index.md for Obsidian navigation. Use --list-stale-gaps to list."
        )


def _entity_alias_map(
    catalog: dict[str, tuple[str, dict[str, object]]], config: WikiConfig
) -> dict[str, tuple[str, str]]:
    """Map lowercased alias/title -> (target_rel, display_name) for linkable
    entities (ontology pages or ENTITY_PAGE_TYPES). Short/common names are dropped."""
    out: dict[str, tuple[str, str]] = {}
    for _page_id, (rel, values) in catalog.items():
        directory = ontology_dir_for(rel, config)
        page_type = str(values.get("page_type", ""))
        if not directory and page_type not in ENTITY_PAGE_TYPES:
            continue
        names: list[str] = []
        title = values.get("title")
        if isinstance(title, str):
            names.append(title)
        names.extend(list_values(values, "aliases"))
        for name in names:
            name = name.strip()
            if len(name) < MENTION_MIN_ALIAS_LEN:
                continue
            low = name.lower()
            if low in MENTION_COMMON_WORDS:
                continue
            out.setdefault(low, (rel, name))
    return out


def _first_markdown_heading(path: Path) -> str:
    for _lineno, line in body_lines_without_frontmatter(path.read_text(encoding="utf-8", errors="replace")):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _canonical_entity_name(value: str) -> str:
    value = ENTITY_TITLE_PREFIX_RE.sub("", value.strip())
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    value = re.sub(r"[_\s-]+", " ", value).strip().lower()
    return value


def _entity_identity_names(rel: str, values: dict[str, object]) -> list[str]:
    names: list[str] = []
    title = values.get("title")
    if isinstance(title, str):
        names.append(title)
    names.extend(list_values(values, "aliases"))
    heading = _first_markdown_heading(ROOT / rel)
    if heading:
        names.append(heading)
    return names


def audit_duplicate_entity_names(errors: list[str], config: WikiConfig) -> None:
    """Block duplicate canonical entity pages.

    Broken navigation is not always a missing file: two person/project/source
    pages can both resolve while splitting the same real entity. This gate keeps
    the entity graph canonical by failing on repeated normalized names.
    """
    seen: dict[str, dict[str, str]] = {}
    catalog = page_catalog(errors, config)
    for _page_id, (rel, values) in catalog.items():
        page_type = str(values.get("page_type", ""))
        if page_type not in ENTITY_CANONICAL_NAME_PAGE_TYPES:
            continue
        for display in _entity_identity_names(rel, values):
            canonical = _canonical_entity_name(display)
            if len(canonical) < MENTION_MIN_ALIAS_LEN or canonical in MENTION_COMMON_WORDS:
                continue
            seen.setdefault(canonical, {}).setdefault(rel, display.strip())
    for canonical, by_rel in sorted(seen.items()):
        if len(by_rel) < 2:
            continue
        locations = ", ".join(
            f"{rel} (`{display}`)" for rel, display in sorted(by_rel.items())
        )
        errors.append(f"duplicate entity canonical name `{canonical}`: {locations}")


def audit_entity_mention_links(
    warnings: list[str], config: WikiConfig, errors: list[str] | None = None
) -> None:
    """Warn on legacy unlinked entity mentions, and optionally error on regressions.

    `audit.mention_links_on_changed: error` escalates only for pages touched in the
    current diff; old stock remains warning-only to avoid gate fatigue.
    """
    prefix = memory_prefix(config)
    alias_map = _entity_alias_map(page_catalog([], config), config)
    if not alias_map:
        return
    changed = changed_paths_for_audit()
    escalate_changed = str(config.audit.get("mention_links_on_changed", "warning")) == "error"
    events_prefix = wiki_paths(config).ingest_events_dir.relative_to(ROOT).as_posix().rstrip("/") + "/"
    pattern = re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(a) for a in sorted(alias_map, key=len, reverse=True)) + r")(?![\w-])",
        re.IGNORECASE,
    )
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        found: dict[str, str] = {}
        for _lineno, line in body_lines_without_frontmatter(text):
            stripped = INLINE_CODE_RE.sub("", MARKDOWN_LINK_RE.sub("", line))
            for match in pattern.finditer(stripped):
                target_rel, display = alias_map[match.group(1).lower()]
                if target_rel == rel:
                    continue
                found.setdefault(display, target_rel)
        if found:
            items = ", ".join(f"{name} ({target})" for name, target in sorted(found.items()))
            message = f"{rel}: names known entities without a link: {items}"
            values, _ = parse_frontmatter(ROOT / rel)
            page_type = str(values.get("page_type") or "")
            if page_type in MENTION_LINK_EXEMPT_PAGE_TYPES:
                continue
            is_ingestion_event = rel.startswith(events_prefix)
            if (
                errors is not None
                and escalate_changed
                and rel in changed
                and page_type != "system_log"
                and not is_ingestion_event
            ):
                errors.append(message)
            else:
                warnings.append(message)


def _string_items(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() and value.strip() != "[]" else []
    return [str(value).strip()] if str(value).strip() else []


def _unlinked_line_text(line: str) -> str:
    return INLINE_CODE_RE.sub("", MARKDOWN_LINK_RE.sub("", line))


def _concept_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", re.IGNORECASE)


def _line_links_target(source_rel: str, line: str, target_rel: str) -> bool:
    for match in MARKDOWN_LINK_RE.finditer(line):
        target = local_link_target_path(source_rel, match.group(1))
        if target is None:
            continue
        try:
            rel = target.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            continue
        if rel == target_rel:
            return True
        if target_rel.endswith("/index.md"):
            target_dir = target_rel.rsplit("/", 1)[0] + "/"
            if rel.startswith(target_dir):
                return True
    return False


def audit_operational_concept_links(errors: list[str], config: WikiConfig) -> None:
    """Require configured context hubs to link recurring operational concepts.

    Entity mention checks cover named pages. This smaller gate covers generic
    process nouns ("source", "claim", "action", "meeting"...) where the target is
    a deliberate operational index. It is opt-in per page to avoid global noise.
    """
    raw = config.audit.get("operational_concept_links") or {}
    if raw in ({}, []):
        return
    if not isinstance(raw, dict):
        errors.append("config: audit.operational_concept_links must be a map")
        return

    for page_rel, targets in sorted(raw.items()):
        page_rel = str(page_rel).strip()
        if not page_rel:
            errors.append("config: audit.operational_concept_links contains empty page path")
            continue
        if not isinstance(targets, dict):
            errors.append(f"config: audit.operational_concept_links.{page_rel} must be a map")
            continue

        page_path = ROOT / page_rel
        if not page_path.exists():
            errors.append(f"{page_rel}: configured operational concept audit page does not exist")
            continue

        linked_targets: dict[str, set[str]] = {}
        for target_rel, terms in sorted(targets.items()):
            target_rel = str(target_rel).strip()
            if not target_rel:
                errors.append(f"{page_rel}: operational concept target is empty")
                continue
            if not (ROOT / target_rel).exists():
                errors.append(f"{page_rel}: operational concept target does not exist: `{target_rel}`")
                continue
            for term in _string_items(terms):
                linked_targets.setdefault(target_rel, set()).add(term)

        if not linked_targets:
            continue

        offenders: dict[str, set[str]] = {}
        text = page_path.read_text(encoding="utf-8", errors="replace")
        for _lineno, line in body_lines_without_frontmatter(text):
            if line.lstrip().startswith("#"):
                continue
            stripped = _unlinked_line_text(line)
            for target_rel, terms in linked_targets.items():
                if _line_links_target(page_rel, line, target_rel):
                    continue
                for term in terms:
                    if _concept_pattern(term).search(stripped):
                        offenders.setdefault(target_rel, set()).add(term)

        for target_rel, terms in sorted(offenders.items()):
            joined = ", ".join(f"`{term}`" for term in sorted(terms, key=str.lower))
            errors.append(
                f"{page_rel}: operational concepts without links to `{target_rel}`: {joined}"
            )


def audit_page_graph(errors: list[str], warnings: list[str], config: WikiConfig) -> None:
    graph = build_page_graph(ROOT, config)
    audit_config = config.audit
    if audit_config.get("orphan_check", False):
        extra_exempt = set(audit_config.get("orphan_exempt_types") or [])
        for rel in orphan_pages(graph, extra_exempt):
            errors.append(f"{rel}: orphan memory page (no inbound body/frontmatter link)")
    if audit_config.get("reachability_check", False):
        root_page = str(
            audit_config.get("reachability_root")
            or f"{memory_prefix(config).rstrip('/')}/index.md"
        )
        for rel in unreachable_pages(graph, root_page):
            errors.append(f"{rel}: unreachable from {root_page}")
    try:
        minimum = int(str(audit_config.get("min_outbound_links", 0) or 0))
    except ValueError:
        errors.append("config: audit.min_outbound_links invalid (integer expected)")
        minimum = 0
    if minimum > 0:
        extra_exempt = set(audit_config.get("orphan_exempt_types") or [])
        for rel in min_outbound_violations(graph, minimum=minimum, exempt_types=extra_exempt):
            warnings.append(f"{rel}: fewer than {minimum} outbound graph links")


def _added_lines_for_path(rel: str) -> list[str]:
    lines: list[str] = []
    for args in (
        ["diff", "--unified=0", "--", rel],
        ["diff", "--cached", "--unified=0", "--", rel],
        ["diff", "--unified=0", "main...HEAD", "--", rel],
        ["diff", "--unified=0", "origin/main...HEAD", "--", rel],
    ):
        for line in run_git(args).splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
    return lines


def _impact_ack_added(config: WikiConfig, affected_rel: str) -> bool:
    ledger = ROOT / str(config.paths.get("impact_acks_page") or "")
    if not str(config.paths.get("impact_acks_page") or "").strip():
        ledger = wiki_paths(config).ingest_dir / "impact-acks.md"
    try:
        ledger_rel = ledger.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    tracked = bool(run_git(["ls-files", "--error-unmatch", ledger_rel]))
    if not ledger.exists() and not tracked:
        return False
    lines = (
        ledger.read_text(encoding="utf-8", errors="replace").splitlines()
        if ledger.exists() and not tracked
        else _added_lines_for_path(ledger_rel)
    )
    for line in lines:
        low = line.lower()
        if affected_rel not in line:
            continue
        if ("afetada:" in low or "affected:" in low) and (
            "sem_impacto:" in low or "no_change:" in low or "reason:" in low
        ):
            return True
    return False


def audit_impact(errors: list[str], config: WikiConfig) -> None:
    if not config.audit.get("impact_check", False):
        return
    graph = build_page_graph(ROOT, config)
    changed_all = changed_paths_for_audit()
    changed = _impact_relevant_changed_paths()
    result = compute_impact(
        graph,
        changed,
        exempt_types=set(config.audit.get("impact_exempt_types") or []),
    )
    if not result.changed_pages:
        return
    for affected in result.affected_pages:
        if affected in changed_all:
            continue
        if _impact_ack_added(config, affected):
            continue
        refs = ", ".join(result.references.get(affected, ()))
        errors.append(
            f"{affected}: impacted by changed page(s) {refs}; update it in this diff "
            "or add a new reasoned line to the impact ack ledger"
        )


def audit_page_type_registry(errors: list[str], config: WikiConfig) -> None:
    if not config.audit.get("page_type_registry_check", False):
        return
    registry = load_page_type_registry(ROOT)
    if registry is None:
        errors.append("wiki.page-types.yaml: missing page type registry")
        return
    if registry.schema_version != PAGE_TYPES_SCHEMA_VERSION:
        errors.append(
            f"{registry.path.relative_to(ROOT).as_posix()}: schema_version must be "
            f"{PAGE_TYPES_SCHEMA_VERSION}"
        )
    for page_type, shape in sorted(registry.page_types.items()):
        error = template_coverage_error(ROOT, page_type, shape)
        if error:
            errors.append(f"{registry.path.relative_to(ROOT).as_posix()}: {error}")

    prefix = memory_prefix(config)
    used_types: set[str] = set()
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        path = ROOT / rel
        values, _ = parse_frontmatter(path)
        page_type = str(values.get("page_type") or "").strip()
        if not page_type:
            continue
        used_types.add(page_type)
        shape = registry.page_types.get(page_type)
        if shape is None:
            errors.append(f"{rel}: page_type `{page_type}` is not declared in wiki.page-types.yaml")
            continue
        errors.extend(validate_shape(ROOT, rel, values, path.read_text(encoding="utf-8"), shape))

    unused = sorted(set(registry.page_types) - used_types)
    for page_type in unused:
        # Notify through warning would be noisy here; unused types are allowed for
        # downstream repos once the shared kit grows a richer base registry.
        _ = page_type


# Consolidation gate: ingestion is only DONE when the wiki's concepts reflect
# the new information. New-style events (generated by wiki_consolidate.py,
# identified by a `source_id:` in the frontmatter) must declare the pages they
# were consolidated into, and each of those pages must reference the source
# back (referential proof of integration — content judgment stays human).
CLAIMS_HEADERS = ("## Claims candidatos", "## Candidate claims")
EMPTY_BULLETS = ("- (nenhum)", "- (none)")


def _claims_section_bullets(text: str) -> list[str]:
    lines = text.splitlines()
    bullets: list[str] = []
    inside = False
    for line in lines:
        if line.strip().startswith("## "):
            inside = line.strip() in CLAIMS_HEADERS
            continue
        if inside and line.strip().startswith("- "):
            if line.strip() not in EMPTY_BULLETS:
                bullets.append(line.strip())
    return bullets


def audit_consolidation(errors: list[str], warnings: list[str], config: WikiConfig) -> None:
    paths = wiki_paths(config)
    events_dir = paths.ingest_events_dir
    if not events_dir.is_dir():
        return
    legacy_unconsolidated = 0
    for event in sorted(events_dir.glob("*.md")):
        if event.name == "README.md":
            continue
        rel = paths.rel(event)
        values, _ = parse_frontmatter(event)
        source_id = str(values.get("source_id") or "").strip()
        consolidated = list_values(values, "consolidated_into")
        if not source_id:
            # Legacy event (pre-consolidation flow): nudge, never block.
            if not consolidated:
                legacy_unconsolidated += 1
            continue
        if not consolidated:
            errors.append(
                f"{rel}: event has no consolidated_into — integrate the new "
                "information into the target pages and list them (ingesting is "
                "integrating, not cataloging)"
            )
        source_refs = set(list_values(values, "source_refs"))
        source_ref = str(values.get("source_ref") or "").strip()
        if source_ref:
            source_refs.add(source_ref)
        for target in consolidated:
            target_path = ROOT / target
            if not target_path.exists():
                errors.append(f"{rel}: consolidated_into path does not exist: `{target}`")
                continue
            if source_refs:
                target_values, _ = parse_frontmatter(target_path)
                target_refs = set(list_values(target_values, "source_refs"))
                if not (target_refs & source_refs):
                    errors.append(
                        f"{rel}: consolidated_into `{target}` does not reference the "
                        f"source back (source_refs missing any of: {', '.join(sorted(source_refs))})"
                    )
        bullets = _claims_section_bullets(event.read_text(encoding="utf-8", errors="replace"))
        claims_linked = list_values(values, "claims")
        no_claim_reason = str(values.get("sem_claim") or values.get("no_claim") or "").strip()
        if bullets and not claims_linked and not no_claim_reason:
            errors.append(
                f"{rel}: candidate claims present but none linked (`claims:`) and no "
                "explicit `sem_claim: <reason>` — claim breakdown cannot be skipped silently"
            )
    if legacy_unconsolidated:
        warnings.append(
            f"{legacy_unconsolidated} legacy event(s) without consolidated_into; "
            "close them when revisiting those sources (wiki_consolidate.py --check)"
        )


def audit_log_changed(errors: list[str], config: WikiConfig) -> None:
    paths = wiki_paths(config)
    prefix = memory_prefix(config)
    log_rel = paths.rel(paths.log_page)
    changed_output = run_git(["diff", "--name-only", "main...HEAD"])
    working_output = run_git(["diff", "--name-only"])
    staged_output = run_git(["diff", "--cached", "--name-only"])
    changed = (
        set(changed_output.splitlines())
        | set(working_output.splitlines())
        | set(staged_output.splitlines())
    )
    memory_changes = {p for p in changed if p.startswith(prefix) and p != log_rel}
    if memory_changes and log_rel not in changed:
        errors.append(f"{prefix.rstrip('/')} changed without updating {log_rel}")


def audit_operation_page(errors: list[str], warnings: list[str], config: WikiConfig) -> None:
    rel = str(config.paths["operation_page"])
    path = ROOT / rel
    if not path.exists():
        errors.append(f"{rel}: missing operation cockpit")
        return
    values, page_errors = parse_frontmatter(path)
    for error in page_errors:
        errors.append(f"{rel}: {error}")
    if values.get("page_type") != "dashboard":
        errors.append(f"{rel}: page_type must be `dashboard`")
    if str(values.get("purpose", "")).strip() == "":
        errors.append(f"{rel}: missing purpose")
    try:
        updated_at = dt.date.fromisoformat(str(values.get("updated_at")))
        stale_after = int(str(values.get("stale_after_days", "0")))
    except ValueError:
        errors.append(f"{rel}: invalid operation updated_at or stale_after_days")
        return
    if stale_after != 1:
        errors.append(f"{rel}: stale_after_days must be 1")
    if updated_at < dt.date.today():
        warnings.append(f"{rel}: operation cockpit is not from today")


def audit_ingestion_events(errors: list[str], config: WikiConfig) -> None:
    paths = wiki_paths(config)
    event_dir = paths.ingest_events_dir
    if not event_dir.exists():
        errors.append(f"{paths.rel(event_dir)}: missing normalized event directory")
        return
    # The four quadrants, each accepted in pt OR en (supports both languages).
    quadrant_concepts = [
        ("Interior individual",),
        ("Exterior individual",),
        ("Interior coletivo", "Interior collective"),
        ("Exterior coletivo", "Exterior collective"),
    ]
    for path in sorted(event_dir.glob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(h in text for h in QUADRANTS_HEADERS):
            errors.append(f"{rel}: missing quadrants section")
        for variants in quadrant_concepts:
            present = next((v for v in variants if v in text), None)
            if present is None:
                errors.append(f"{rel}: missing quadrant `{variants[0]}`")
                continue
            # Content: the quadrant's table cell cannot be empty/placeholder.
            for line in text.splitlines():
                if line.lstrip().startswith("|") and present in line:
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    content = " ".join(cells[1:]).strip().lower()
                    if not content or any(ph in content for ph in QUADRANT_PLACEHOLDERS):
                        errors.append(f"{rel}: quadrant `{present}` not filled (placeholder/empty)")
                    break


def audit_ingestion_absolute_paths(errors: list[str], config: WikiConfig) -> None:
    # Missing ingest dir is reported loudly by audit_ingestion_events (the
    # events dir lives under it); here it just makes this check inapplicable.
    ingest_dir = wiki_paths(config).ingest_dir
    if not ingest_dir.exists():
        return
    for path in sorted(ingest_dir.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in body_lines_without_frontmatter(path.read_text(encoding="utf-8", errors="replace")):
            without_links = MARKDOWN_LINK_RE.sub("", line)
            for match in ABSOLUTE_USER_PATH_RE.finditer(without_links):
                absolute = match.group(0).rstrip(".,)")
                if not line_has_link_for_path(line, Path(absolute).name):
                    errors.append(f"{rel}:{lineno}: absolute local source path must be a markdown link: `{absolute}`")
            if HOME_TRAVERSAL_RE.search(without_links):
                errors.append(f"{rel}:{lineno}: path traversal to home Downloads is not portable")


# Keywords proving a publication/redaction checklist exists on the page.
# Superset of Portuguese and English terms: compatibility for localized repos.
PUBLIC_CHECKLIST_KEYWORDS = ("redacao", "redaction", "publicacao", "publication", "checklist")


def audit_public_candidates(errors: list[str], config: WikiConfig) -> None:
    """Scans ALL public_candidate pages (not just the diff): requires a redaction
    checklist and that no secret/PII is exposed."""
    prefix = memory_prefix(config)
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        path = ROOT / rel
        values, _ = parse_frontmatter(path)
        if values.get("visibility") != "public_candidate":
            continue
        low = path.read_text(encoding="utf-8", errors="replace").lower()
        if not any(keyword in low for keyword in PUBLIC_CHECKLIST_KEYWORDS):
            errors.append(f"{rel}: public_candidate missing publication/redaction checklist")
        for finding in scan_file(path):
            if finding.category in {"secret", "pii"}:
                errors.append(f"{rel}:{finding.line}: public_candidate contains {finding.category} {finding.kind} ({finding.excerpt})")


def audit_ingestion_proposals_gate_state(errors: list[str], config: WikiConfig) -> None:
    """Every ingestion proposal (flat in the configured ingest dir) must carry
    a valid gate_state — the live gate only works if the proposals enter it.

    Missing ingest dir is reported loudly by audit_ingestion_events."""
    ingest_dir = wiki_paths(config).ingest_dir
    if not ingest_dir.is_dir():
        return
    for path in sorted(ingest_dir.glob("*.md")):
        if path.name in {"README.md", "impact-acks.md"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        values, _ = parse_frontmatter(path)
        state = values.get("gate_state")
        if not state:
            errors.append(f"{rel}: ingestion proposal without gate_state")
        elif str(state) not in GATE_STATES:
            errors.append(f"{rel}: invalid gate_state `{state}`")


def audit_promotion_gate(errors: list[str], config: WikiConfig) -> None:
    """Visibility promotion (public page or marked promoted_from) requires the
    v5 consent/anonymization/revert fields."""
    prefix = memory_prefix(config)
    for rel in markdown_files():
        if not rel.startswith(prefix):
            continue
        values, _ = parse_frontmatter(ROOT / rel)
        if "promoted_from" not in values and str(values.get("visibility")) != "public":
            continue
        missing = [field for field in PROMOTION_REQUIRED_FIELDS if field not in values]
        if missing:
            errors.append(f"{rel}: visibility promotion without required fields: {', '.join(missing)}")


def audit_context_pass_gate(
    errors: list[str], config: WikiConfig, warnings: list[str] | None = None
) -> None:
    """LLM pass honesty gate: with required_context_pass=true, no source with an
    emitted context package may have a chunk without a recorded result.

    ORPHAN requests are skipped (aggregated warning, not error): a request whose
    source_id starts with `query-` (ad-hoc search, no chunks file) or whose
    chunks file <derived_root>/chunks/<source_id>.json no longer exists
    (source re-edited/gc'd) would otherwise lock the gate red permanently.
    """
    if not config.llm.get("required_context_pass", True):
        return
    paths = wiki_paths(config)
    req_dir = paths.extraction_events
    cache_dir = paths.llm_cache
    chunks_dir = paths.chunks
    if not req_dir.exists():
        return
    suffix = "-llm-context-request.json"
    orphans: list[str] = []
    for path in sorted(req_dir.glob(f"*{suffix}")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt JSON must NOT disarm the gate silently (finding 12):
            # deleting/corrupting the request closed the gate with no error.
            errors.append(f"{rel}: unreadable LLM pass request (invalid JSON)")
            continue
        source_id = str(data.get("source_id") or path.name[: -len(suffix)])
        if source_id.startswith("query-") or not (chunks_dir / f"{source_id}.json").exists():
            orphans.append(rel)
            continue
        pending = [
            chunk for chunk in data.get("chunks", [])
            if not (cache_dir / f"{chunk.get('cache_key')}.json").exists()
        ]
        if pending:
            errors.append(
                f"{rel}: pending LLM pass in {len(pending)} chunk(s) with required_context_pass=true"
            )
    if orphans and warnings is not None:
        warnings.append(
            f"{len(orphans)} orphan LLM context request(s) skipped by the gate "
            "(query-scoped or chunks file gone; source re-edited/gc'd): "
            + ", ".join(orphans)
        )


PROMPTS_DIR_REL = "wiki_core/llm/prompts"
PROMPT_CHECKSUMS_NAME = ".checksums"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def audit_prompt_checksums(errors: list[str]) -> None:
    """Versioned prompts must not drift silently.

    `wiki_core/llm/prompts/.checksums` pins `sha256  filename` for every prompt.
    The auditor ERRORS when a prompt's sha does not match: a prompt change is a
    conscious decision — either update the checksum in the same PR, or bump the
    prompt version (new file + new pinned line).
    """
    prompts_dir = ROOT / PROMPTS_DIR_REL
    if not prompts_dir.is_dir():
        return
    rel_checksums = f"{PROMPTS_DIR_REL}/{PROMPT_CHECKSUMS_NAME}"
    prompts = sorted(p.name for p in prompts_dir.glob("*.md"))
    checksums_path = prompts_dir / PROMPT_CHECKSUMS_NAME
    if not checksums_path.exists():
        if prompts:
            errors.append(
                f"{rel_checksums}: missing prompt checksums file "
                "(pin `sha256  filename` for each prompt)"
            )
        return
    pinned: dict[str, str] = {}
    for lineno, raw in enumerate(checksums_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]):
            errors.append(
                f"{rel_checksums}:{lineno}: invalid checksum line (expected `sha256  filename`)"
            )
            continue
        pinned[parts[1]] = parts[0]
    for name in prompts:
        actual = hashlib.sha256((prompts_dir / name).read_bytes()).hexdigest()
        expected = pinned.get(name)
        if expected is None:
            errors.append(
                f"{PROMPTS_DIR_REL}/{name}: prompt not pinned in {PROMPT_CHECKSUMS_NAME} "
                "(add its `sha256  filename` line)"
            )
        elif actual != expected:
            errors.append(
                f"{PROMPTS_DIR_REL}/{name}: prompt checksum mismatch — prompt changed "
                "without a conscious decision (update .checksums in the same PR or "
                "bump the prompt version)"
            )
    for name in sorted(set(pinned) - set(prompts)):
        errors.append(f"{rel_checksums}: pinned prompt does not exist: {name}")


def audit_llm_cache_metadata(errors: list[str], config: WikiConfig | None = None) -> None:
    # `config` is optional for callers auditing a default-layout tree (e.g. the
    # e2e gate test); without it the layout resolves from the config at ROOT.
    cache_dir = wiki_paths(config or load_config(ROOT)).llm_cache
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.glob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for required in ("prompt_version", "schema_version", "cache_key"):
            if required not in text:
                errors.append(f"{rel}: cache result missing `{required}`")


def audit_perspective_coverage(errors: list[str], config: WikiConfig) -> None:
    if not config.audit.get("perspective_coverage_check", False):
        return
    paths = wiki_paths(config)
    req_dir = paths.extraction_events
    cache_dir = paths.llm_cache
    if not req_dir.exists():
        return
    catalog = page_catalog([], config)
    perspective_ids = {
        page_id
        for page_id, (_rel, values) in catalog.items()
        if str(values.get("page_type") or "") == "perspective"
    }
    for request_path in sorted(req_dir.glob("*-llm-context-request.json")):
        rel = request_path.relative_to(ROOT).as_posix()
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        required = [str(item) for item in request.get("perspectives_required") or []]
        if not required:
            continue
        for perspective_id in required:
            if perspective_id not in perspective_ids:
                errors.append(f"{rel}: required perspective `{perspective_id}` is not a perspective page")
        for chunk in request.get("chunks", []):
            key = str(chunk.get("cache_key") or "")
            result_path = cache_dir / f"{key}.json"
            if not result_path.exists():
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                errors.append(f"{result_path.relative_to(ROOT).as_posix()}: invalid JSON")
                continue
            perspectives = result.get("perspectives")
            if not isinstance(perspectives, dict):
                errors.append(f"{result_path.relative_to(ROOT).as_posix()}: missing perspectives object")
                continue
            for perspective_id in required:
                block = perspectives.get(perspective_id)
                if not isinstance(block, dict):
                    errors.append(
                        f"{result_path.relative_to(ROOT).as_posix()}: missing required perspective `{perspective_id}`"
                    )
                    continue
                status = str(block.get("status") or "")
                if not status:
                    errors.append(
                        f"{result_path.relative_to(ROOT).as_posix()}: perspective `{perspective_id}` missing status"
                    )


def audit_source_config_perspectives(errors: list[str], config: WikiConfig) -> None:
    if not config.audit.get("perspective_coverage_check", False):
        return
    catalog = page_catalog([], config)
    perspective_ids = {
        page_id
        for page_id, (_rel, values) in catalog.items()
        if str(values.get("page_type") or "") == "perspective"
    }
    for _page_id, (rel, values) in sorted(catalog.items()):
        if str(values.get("page_type") or "") != "source_config":
            continue
        for field in ("perspectives_required", "perspectives_optional"):
            for perspective_id in list_values(values, field):
                if perspective_id not in perspective_ids:
                    errors.append(f"{rel}: {field} `{perspective_id}` is not a perspective page")


def _closure_pages(value: object) -> tuple[set[str], dict[str, str]]:
    pages: set[str] = set()
    reasons: dict[str, str] = {}
    if not isinstance(value, list):
        return pages, reasons
    for item in value:
        if isinstance(item, str):
            pages.add(item)
        elif isinstance(item, dict):
            page = str(item.get("page") or item.get("path") or "").strip()
            if page:
                pages.add(page)
                reasons[page] = str(item.get("reason") or "").strip()
    return pages, reasons


def audit_impact_closure(errors: list[str], config: WikiConfig) -> None:
    if not config.audit.get("impact_closure_check", False):
        return
    events_dir = wiki_paths(config).ingest_events_dir
    if not events_dir.is_dir():
        return
    for path in sorted(events_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        values = parse_yaml_frontmatter(path)
        affected = values.get("affected_pages")
        if not isinstance(affected, dict):
            continue
        must_update = {str(item) for item in affected.get("must_update") or []}
        if not must_update:
            continue
        closure = values.get("impact_closure")
        if not isinstance(closure, dict):
            errors.append(f"{rel}: affected_pages.must_update present without impact_closure")
            continue
        updated, _ = _closure_pages(closure.get("updated"))
        no_change, no_change_reasons = _closure_pages(closure.get("no_change"))
        blocked, blocked_reasons = _closure_pages(closure.get("blocked"))
        closed = updated | no_change | blocked
        for page in sorted(must_update - closed):
            errors.append(f"{rel}: must_update `{page}` is not closed in impact_closure")
        for page in sorted(no_change):
            if not no_change_reasons.get(page):
                errors.append(f"{rel}: impact_closure.no_change `{page}` missing reason")
        for page in sorted(blocked):
            if not blocked_reasons.get(page):
                errors.append(f"{rel}: impact_closure.blocked `{page}` missing reason")


class AuditContext:
    """Shared state threaded through every registered check.

    Bundles the mutable `errors`/`warnings` accumulators, the loaded
    `config`, and the run-time flag (`public_export`) that a couple of checks
    need. Keeping this in one object lets the CHECKS registry stay declarative:
    each runner takes a single `ctx` argument and forwards exactly the same
    positional/keyword arguments the old hand-written main() used.
    """

    __slots__ = ("errors", "warnings", "config", "public_export")

    def __init__(self, config: WikiConfig, public_export: bool = False) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.config = config
        self.public_export = public_export


# Declarative audit registry: ordered (name, runner) pairs. The order and the
# exact arguments each runner forwards MUST match the historical hand-written
# call sequence in main() -- the 8 honesty gates depend on identical behavior
# (same checks, same order, same output, same exit code). Adding a check means
# appending an entry; --only filters this list without reordering it.
#
# Each runner receives the shared AuditContext and dispatches to the underlying
# audit_* function with its original signature. Checks that emit errors and
# warnings, errors-only, or warnings-only all funnel through the same ctx
# accumulators, preserving the errors-vs-warnings separation (warnings never
# block).
CHECKS: tuple[tuple[str, "callable"], ...] = (
    ("frontmatter", lambda ctx: audit_frontmatter(ctx.errors, ctx.warnings, ctx.config)),
    ("stale_coverage", lambda ctx: audit_stale_coverage(ctx.warnings, ctx.config)),
    ("freshness_budget", lambda ctx: audit_freshness_budget(ctx.errors, ctx.warnings, ctx.config)),
    ("drive_artifact_links", lambda ctx: audit_drive_artifact_links(ctx.warnings, ctx.config)),
    ("command_reference", lambda ctx: audit_command_reference(ctx.errors, ctx.config)),
    ("relations", lambda ctx: audit_relations(ctx.errors, ctx.config)),
    ("old_paths", lambda ctx: audit_old_paths(ctx.errors, ctx.config)),
    ("secrets", lambda ctx: audit_secrets(ctx.errors, ctx.config)),
    ("pii", lambda ctx: audit_pii(ctx.errors, ctx.warnings, ctx.config, public_export=ctx.public_export)),
    ("clickable_local_links", lambda ctx: audit_clickable_local_links(ctx.errors, ctx.config)),
    ("obsidian_directory_links", lambda ctx: audit_obsidian_directory_links(ctx.warnings, ctx.config)),
    ("page_graph", lambda ctx: audit_page_graph(ctx.errors, ctx.warnings, ctx.config)),
    ("page_type_registry", lambda ctx: audit_page_type_registry(ctx.errors, ctx.config)),
    ("duplicate_entity_names", lambda ctx: audit_duplicate_entity_names(ctx.errors, ctx.config)),
    ("entity_mention_links", lambda ctx: audit_entity_mention_links(ctx.warnings, ctx.config, ctx.errors)),
    ("operational_concept_links", lambda ctx: audit_operational_concept_links(ctx.errors, ctx.config)),
    ("impact", lambda ctx: audit_impact(ctx.errors, ctx.config)),
    ("operation_page", lambda ctx: audit_operation_page(ctx.errors, ctx.warnings, ctx.config)),
    ("ingestion_events", lambda ctx: audit_ingestion_events(ctx.errors, ctx.config)),
    ("consolidation", lambda ctx: audit_consolidation(ctx.errors, ctx.warnings, ctx.config)),
    ("ingestion_proposals_gate_state", lambda ctx: audit_ingestion_proposals_gate_state(ctx.errors, ctx.config)),
    ("ingestion_absolute_paths", lambda ctx: audit_ingestion_absolute_paths(ctx.errors, ctx.config)),
    ("public_candidates", lambda ctx: audit_public_candidates(ctx.errors, ctx.config)),
    ("promotion_gate", lambda ctx: audit_promotion_gate(ctx.errors, ctx.config)),
    ("context_pass_gate", lambda ctx: audit_context_pass_gate(ctx.errors, ctx.config, ctx.warnings)),
    ("prompt_checksums", lambda ctx: audit_prompt_checksums(ctx.errors)),
    ("llm_cache_metadata", lambda ctx: audit_llm_cache_metadata(ctx.errors, ctx.config)),
    ("source_config_perspectives", lambda ctx: audit_source_config_perspectives(ctx.errors, ctx.config)),
    ("perspective_coverage", lambda ctx: audit_perspective_coverage(ctx.errors, ctx.config)),
    ("impact_closure", lambda ctx: audit_impact_closure(ctx.errors, ctx.config)),
    ("log_changed", lambda ctx: audit_log_changed(ctx.errors, ctx.config)),
)

# Ordered names only -- introspectable without building a context (used by
# --only validation and the registry coverage test).
CHECK_NAMES: tuple[str, ...] = tuple(name for name, _ in CHECKS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="return non-zero on errors")
    parser.add_argument(
        "--public-export",
        action="store_true",
        help="pre-publication mode: error for PII on ANY page (not just public ones)",
    )
    parser.add_argument(
        "--strict-local",
        action="store_true",
        help="real-environment mode: require links to derived/raw artifacts to exist on disk",
    )
    parser.add_argument(
        "--list-stale-gaps",
        action="store_true",
        help="lists each memory page without declared freshness (instead of the total)",
    )
    parser.add_argument(
        "--only",
        metavar="NAME[,NAME...]",
        help=(
            "run only the named checks (comma-separated), in registry order; "
            "speeds up the dev loop. Names match the CHECKS registry; use "
            "--list-checks to see them."
        ),
    )
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="print the registered check names in run order and exit",
    )
    args = parser.parse_args()

    if args.list_checks:
        for name in CHECK_NAMES:
            print(name)
        return 0

    selected = CHECKS
    if args.only:
        requested = [name.strip() for name in args.only.split(",") if name.strip()]
        unknown = [name for name in requested if name not in CHECK_NAMES]
        if unknown:
            known = ", ".join(CHECK_NAMES)
            parser.error(f"unknown check(s): {', '.join(unknown)}. known: {known}")
        wanted = set(requested)
        # Preserve registry order regardless of the order names were passed.
        selected = tuple((name, run) for name, run in CHECKS if name in wanted)

    global STRICT_LOCAL, LIST_STALE_GAPS
    STRICT_LOCAL = args.strict_local
    LIST_STALE_GAPS = args.list_stale_gaps
    tracked_files.cache_clear()  # fresh file set on each invocation
    parse_frontmatter.cache_clear()  # fresh frontmatter parses on each invocation

    config = load_config(ROOT)
    build_local_path_regexes(config)

    ctx = AuditContext(config, public_export=args.public_export)
    for _name, run in selected:
        run(ctx)
    errors = ctx.errors
    warnings = ctx.warnings

    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"wiki_audit: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if args.check and errors else 0


if __name__ == "__main__":
    sys.exit(main())
