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
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config
from wiki_core.detectors import scan_file
from wiki_core.gate import STATES as GATE_STATES

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

# Core method pages (generic, valid in any repo). The CONTEXT pages
# (memorias/<ctx>/index.md) are driven by `contexts` in the config, so we don't
# hardcode the contexts of a specific repo.
CORE_PAGES = [
    "memorias/index.md",
    "memorias/sistema/log.md",
    "memorias/sistema/revisao-docs.md",
    "memorias/sistema/contrato-wiki-operacional.md",
    "memorias/sistema/processo-ingestao.md",
    "memorias/sistema/aprovacoes-git.md",
    "memorias/sistema/cobertura-wiki.md",
    "memorias/sistema/ingestao/README.md",
]


def primary_pages(config: WikiConfig) -> list[str]:
    """Required pages: method core + one hub per declared context."""
    return CORE_PAGES + [f"memorias/{ctx}/index.md" for ctx in config.contexts]

ONTOLOGY_DIR_TYPES = {
    "memorias/ontologia": {"ontology_index", "operational_rule"},
    "memorias/pessoas": {"ontology_index", "person", "profile"},
    "memorias/holons": {"ontology_index", "holon"},
    "memorias/papeis": {"ontology_index", "role"},
    "memorias/responsabilidades": {"ontology_index", "responsibility"},
    "memorias/atribuicoes": {"ontology_index", "assignment"},
    "memorias/projetos": {"ontology_index", "project"},
    "memorias/iniciativas": {"ontology_index", "initiative"},
    "memorias/fontes": {"ontology_index", "source", "source_catalog", "artifact"},
    "memorias/claims": {"ontology_index", "claim"},
    "memorias/decisoes": {"ontology_index", "decision"},
    "memorias/insights": {"ontology_index", "insight"},
    "memorias/acoes": {"ontology_index", "action"},
    "memorias/timelines": {"ontology_index", "timeline"},
    "memorias/evidencias": {"ontology_index", "evidence"},
    "memorias/cobertura": {"ontology_index", "coverage"},
}

RELATION_PREFIXES = {
    "owner": ("pessoa-", "papel-", "holon-"),
    "related_holons": ("holon-",),
    "roles": ("papel-",),
    "responsibilities": ("responsabilidade-",),
    "source_refs": ("fonte-", "evidencia-"),
    "claims": ("claim-",),
    "decisions": ("decisao-",),
    "actions": ("acao-",),
}

ALLOWED_OLD_PATH_REFERENCES = {
    ".github/pull_request_template.md",
    "docs/referencias/propostas/analise-critica-pontos-corrigir-metodologia-wiki-2026-06-09.md",
    "docs/referencias/propostas/avaliacao-critica-wiki-viva-2026-06-09.md",
    "docs/referencias/templates/wiki/pr-checklist.md",
    "memorias/sistema/revisao-docs.md",
}

LINK_AUDIT_FILES = {
    ".github/pull_request_template.md",
    "AGENTS.md",
}

LOCAL_PATH_PREFIX_RE = re.compile(
    r"^(?:AGENTS\.md|memorias(?:/|$)|docs(?:/|$)|data(?:/|$)|scripts(?:/|$)|"
    r"\.github(?:/|$)|\.skills(?:/|$))"
)

INLINE_CODE_LOCAL_PATH_RE = re.compile(
    r"`((?:AGENTS\.md|memorias|docs|data|scripts|\.github|\.skills)(?:/|\b)[^`\n]*)`"
)

BARE_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(AGENTS\.md|(?:memorias|docs|data|scripts|\.github|\.skills)/[A-Za-z0-9_./*%-]+)"
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Fixed: stops at the first space/boundary (the old version swallowed the
# following prose with the space inside the character class, making the check inert).
ABSOLUTE_USER_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+/[^\s)\]]+")
# A traversal disguised as relative that climbs up to the author's home (e.g. ../../../../Downloads/...).
HOME_TRAVERSAL_RE = re.compile(r"(?:\.\./){2,}[^\s)\]]*Downloads[^\s)\]]*")

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

# Strict local mode (--strict-local): requires links to derived/raw artifacts
# (gitignored) to actually exist on disk. Default False for clean clone/CI.
STRICT_LOCAL = False

# --list-stale-gaps: lists each memory page without declared freshness (instead
# of just the total). The check itself does not fail (warning) until the owner
# triages the windows.
LIST_STALE_GAPS = False


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        return ""


@functools.lru_cache(maxsize=1)
def tracked_files() -> list[str]:
    # Memoized: it was called ~8x per run (each audit_* via markdown_files),
    # running 2 git subprocesses per call — ~16 git forks per audit.
    # The file set does not change during a run; main() clears the cache.
    tracked = run_git(["ls-files"])
    untracked = run_git(["ls-files", "--others", "--exclude-standard"])
    return sorted({line for output in (tracked, untracked) for line in output.splitlines() if line})


def markdown_files() -> list[str]:
    return [rel for rel in tracked_files() if rel.endswith(".md")]


def link_audit_files() -> list[str]:
    files = []
    for rel in markdown_files():
        if (
            rel.startswith("memorias/")
            or rel.startswith("docs/referencias/templates/wiki/")
            or rel in LINK_AUDIT_FILES
            or rel.startswith(".skills/")
        ):
            files.append(rel)
    return sorted(files)


def ontology_dir_for(rel: str) -> str | None:
    for directory in ONTOLOGY_DIR_TYPES:
        if rel.startswith(f"{directory}/"):
            return directory
    return None


def _unquote(value: str) -> str:
    """Remove a single/double quote pair around a frontmatter value.

    Without this, `visibility: "public_candidate"` was parsed WITH the quotes and
    did not match PUBLIC_VISIBILITIES — the public page escaped the PII block
    (finding 15).
    """
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


@functools.lru_cache(maxsize=None)
def parse_frontmatter(path: Path) -> tuple[dict[str, object], list[str]]:
    # Memoized per path: several audit_* checks re-parse the same pages within a
    # single run (frontmatter, stale coverage, relations, PII, promotion...).
    # The file set does not change during a run; main() clears the cache.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, ["missing frontmatter block"]
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, ["unterminated frontmatter block"]

    values: dict[str, object] = {}
    errors: list[str] = []
    current_key: str | None = None
    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw.startswith((" ", "\t")) and stripped.startswith("- ") and current_key:
            current = values.setdefault(current_key, [])
            if isinstance(current, list):
                current.append(_unquote(stripped[2:].strip()))
            continue
        if ":" not in raw:
            errors.append(f"invalid frontmatter line: {raw}")
            current_key = None
            continue
        key, value = raw.split(":", 1)
        current_key = key.strip()
        value = _unquote(value.strip())
        if value == "[]":
            values[current_key] = []
        elif value:
            values[current_key] = value
        else:
            values[current_key] = []

    missing = sorted(REQUIRED_KEYS - values.keys())
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    return values, errors


def list_values(values: dict[str, object], key: str) -> list[str]:
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


def local_link_target_exists(source_rel: str, href: str) -> bool:
    href = href.split("#", 1)[0]
    if not href:
        return True
    if is_external_link(href):
        return True
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
        return True
    if rel.startswith(GITIGNORED_LINK_PREFIXES):
        # By default we tolerate links to derived/raw artifacts (gitignored): a
        # clean clone/CI does not have them. In --strict-local we require them to
        # actually exist on disk (catches a dangling derived reference in a real env).
        return target.exists() if STRICT_LOCAL else True
    return target.exists()


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


def page_catalog(errors: list[str]) -> dict[str, tuple[str, dict[str, object]]]:
    catalog: dict[str, tuple[str, dict[str, object]]] = {}
    for rel in markdown_files():
        if not rel.startswith("memorias/"):
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
    pages.update(rel for rel in markdown_files() if ontology_dir_for(rel))
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

        directory = ontology_dir_for(rel)
        if directory:
            missing_relations = sorted(RELATION_KEYS - values.keys())
            if missing_relations:
                errors.append(f"{rel}: missing relation keys: {', '.join(missing_relations)}")
            page_type = str(values.get("page_type", ""))
            allowed = ONTOLOGY_DIR_TYPES[directory]
            if page_type not in allowed:
                errors.append(f"{rel}: page_type `{page_type}` not allowed in {directory}")


# Extension relaxed to [A-Za-z0-9]{1,8}: the old [a-z]{2,4} missed .jsonl,
# .sqlite and other longer/mixed-case extensions, letting unversioned-artifact
# links escape the audit.
LOCAL_ARTIFACT_LINK_RE = re.compile(
    r"\]\((?:\.\./)+data/(?:raw|derived)/[^)]*\.[A-Za-z0-9]{1,8}\)"
)

COMMAND_REFERENCE_PAGE = "memorias/sistema/wiki/referencia-comandos.md"


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


def audit_command_reference(errors: list[str]) -> None:
    """Doc-code gate of the meta-wiki (P2): the command reference must not drift.

    Every tracked `scripts/wiki_*.py` CLI must be cited in
    referencia-comandos.md, and every `wiki_*.py` cited there must exist in the repo.
    Cheap to maintain (one row in the table) and kills silent doc-code drift.
    """
    ref_path = ROOT / COMMAND_REFERENCE_PAGE
    if not ref_path.exists():
        return
    text = ref_path.read_text(encoding="utf-8")
    tracked_clis = {
        Path(rel).name
        for rel in tracked_files()
        if rel.startswith("scripts/wiki_") and rel.endswith(".py")
    }
    mentioned = set(re.findall(r"\b(wiki_[a-z0-9_]+\.py)\b", text))
    for name in sorted(tracked_clis - mentioned):
        errors.append(f"{COMMAND_REFERENCE_PAGE}: undocumented CLI: {name}")
    for name in sorted(mentioned - tracked_clis):
        errors.append(f"{COMMAND_REFERENCE_PAGE}: documented but nonexistent CLI: {name}")


def audit_drive_artifact_links(warnings: list[str]) -> None:
    """General rule: the wiki must not link to an unversioned local FILE.

    A link to a file under data/raw/** or data/derived/** (gitignored) breaks on
    GitHub. The content should live in the personal Drive folder (id in .env) via
    `scripts/wiki_drive_publish.py`, and the page should point to the view_url of
    the versioned manifest data/drive_artifacts_manifest.json. Links to VERSIONED
    files inside data/ (e.g. manifest, versioned rules) are ok.
    Aggregated warning (extensive historical legacy); the list comes out with --list-stale-gaps.
    """
    tracked = set(tracked_files())
    offenders: dict[str, int] = {}
    for rel in markdown_files():
        if not rel.startswith("memorias/"):
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
    memory_root = str(config.paths.get("memory_root", "memorias")).rstrip("/") + "/"
    today = dt.date.today()
    already = set(primary_pages(config))
    already.update(rel for rel in markdown_files() if ontology_dir_for(rel))
    gaps: list[str] = []
    for rel in markdown_files():
        if not rel.startswith(memory_root) or rel in already:
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


def audit_relations(errors: list[str]) -> None:
    catalog = page_catalog(errors)
    page_ids = set(catalog)
    for rel in markdown_files():
        if not rel.startswith("memorias/") or not ontology_dir_for(rel):
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


def audit_old_paths(errors: list[str]) -> None:
    for rel in [line for line in run_git(["ls-files"]).splitlines() if line]:
        if rel.startswith("docs/2026/") or rel.startswith("docs/memorias/"):
            errors.append(f"{rel}: old docs path is still tracked")
        if not rel.endswith(".md"):
            continue
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        if ("docs/2026" in text or "docs/memorias" in text) and rel not in ALLOWED_OLD_PATH_REFERENCES:
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
    for rel in markdown_files():
        if not rel.startswith("memorias/"):
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


def audit_clickable_local_links(errors: list[str]) -> None:
    for rel in link_audit_files():
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


def audit_log_changed(errors: list[str]) -> None:
    changed_output = run_git(["diff", "--name-only", "main...HEAD"])
    working_output = run_git(["diff", "--name-only"])
    staged_output = run_git(["diff", "--cached", "--name-only"])
    changed = (
        set(changed_output.splitlines())
        | set(working_output.splitlines())
        | set(staged_output.splitlines())
    )
    memory_changes = {
        p for p in changed if p.startswith("memorias/") and p != "memorias/sistema/log.md"
    }
    if memory_changes and "memorias/sistema/log.md" not in changed:
        errors.append("memorias changed without updating memorias/sistema/log.md")


def audit_operation_page(errors: list[str], warnings: list[str]) -> None:
    rel = "memorias/operacao.md"
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


def audit_ingestion_events(errors: list[str]) -> None:
    event_dir = ROOT / "memorias/sistema/ingestao/eventos"
    if not event_dir.exists():
        errors.append("memorias/sistema/ingestao/eventos: missing normalized event directory")
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


def audit_ingestion_absolute_paths(errors: list[str]) -> None:
    ingest_dir = ROOT / "memorias/sistema/ingestao"
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


def audit_public_candidates(errors: list[str]) -> None:
    """Scans ALL public_candidate pages (not just the diff): requires a redaction
    checklist and that no secret/PII is exposed."""
    for rel in markdown_files():
        if not rel.startswith("memorias/"):
            continue
        path = ROOT / rel
        values, _ = parse_frontmatter(path)
        if values.get("visibility") != "public_candidate":
            continue
        low = path.read_text(encoding="utf-8", errors="replace").lower()
        if "redacao" not in low and "publicacao" not in low and "checklist" not in low:
            errors.append(f"{rel}: public_candidate missing publication/redaction checklist")
        for finding in scan_file(path):
            if finding.category in {"secret", "pii"}:
                errors.append(f"{rel}:{finding.line}: public_candidate contains {finding.category} {finding.kind} ({finding.excerpt})")


def audit_ingestion_proposals_gate_state(errors: list[str]) -> None:
    """Every ingestion proposal (flat in memorias/sistema/ingestao/) must carry
    a valid gate_state — the live gate only works if the proposals enter it."""
    ingest_dir = ROOT / "memorias/sistema/ingestao"
    if not ingest_dir.is_dir():
        return
    for path in sorted(ingest_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        values, _ = parse_frontmatter(path)
        state = values.get("gate_state")
        if not state:
            errors.append(f"{rel}: ingestion proposal without gate_state")
        elif str(state) not in GATE_STATES:
            errors.append(f"{rel}: invalid gate_state `{state}`")


def audit_promotion_gate(errors: list[str]) -> None:
    """Visibility promotion (public page or marked promoted_from) requires the
    v5 consent/anonymization/revert fields."""
    for rel in markdown_files():
        if not rel.startswith("memorias/"):
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
    chunks file data/derived/wiki/chunks/<source_id>.json no longer exists
    (source re-edited/gc'd) would otherwise lock the gate red permanently.
    """
    if not config.llm.get("required_context_pass", True):
        return
    req_dir = ROOT / "data/derived/wiki/extraction-events"
    cache_dir = ROOT / "data/derived/wiki/llm-cache"
    chunks_dir = ROOT / "data/derived/wiki/chunks"
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


def audit_llm_cache_metadata(errors: list[str]) -> None:
    cache_dir = ROOT / "data/derived/wiki/llm-cache"
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.glob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for required in ("prompt_version", "schema_version", "cache_key"):
            if required not in text:
                errors.append(f"{rel}: cache result missing `{required}`")


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
    args = parser.parse_args()

    global STRICT_LOCAL, LIST_STALE_GAPS
    STRICT_LOCAL = args.strict_local
    LIST_STALE_GAPS = args.list_stale_gaps
    tracked_files.cache_clear()  # fresh file set on each invocation
    parse_frontmatter.cache_clear()  # fresh frontmatter parses on each invocation

    config = load_config(ROOT)

    errors: list[str] = []
    warnings: list[str] = []
    audit_frontmatter(errors, warnings, config)
    audit_stale_coverage(warnings, config)
    audit_freshness_budget(errors, warnings, config)
    audit_drive_artifact_links(warnings)
    audit_command_reference(errors)
    audit_relations(errors)
    audit_old_paths(errors)
    audit_secrets(errors, config)
    audit_pii(errors, warnings, config, public_export=args.public_export)
    audit_clickable_local_links(errors)
    audit_operation_page(errors, warnings)
    audit_ingestion_events(errors)
    audit_ingestion_proposals_gate_state(errors)
    audit_ingestion_absolute_paths(errors)
    audit_public_candidates(errors)
    audit_promotion_gate(errors)
    audit_context_pass_gate(errors, config, warnings)
    audit_prompt_checksums(errors)
    audit_llm_cache_metadata(errors)
    audit_log_changed(errors)

    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"wiki_audit: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if args.check and errors else 0


if __name__ == "__main__":
    sys.exit(main())
