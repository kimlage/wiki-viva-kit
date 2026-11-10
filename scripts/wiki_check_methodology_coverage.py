#!/usr/bin/env python3
"""PRESENCE AND CONTENT check of the living wiki methodology (v5).

This verifier does NOT limit itself to checking that files exist: each required
file must have real content (not empty, not placeholder), frontmatter with the
minimal fields and the content sections prescribed by the methodology. The LLM
pass gate is portable (discovered from the versioned derived artifacts in the
repo) and never accepts the mere existence of an LLM *plan* as proof of an
executed pass.

No absolute paths: nothing here depends on files outside the repository. When it
is necessary to validate artifacts derived from a source, the source_id is
discovered by scanning the source-manifests directory under the configured
derived root (default `data/derived/wiki/source-manifests/*.json`).

All required page/template paths come from `wiki.config.yaml` (cfg.coverage and
cfg.paths), so localized repos pin their own layout without code changes.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
from scripts._common import ROOT

from wiki_core.traversal import wiki_markdown_files
from wiki_core.llm.context_pass import read_matching_result
from wiki_core.config import WikiConfig, config_from_mapping, load_config
from wiki_core.frontmatter import parse_frontmatter as canonical_parse_frontmatter
from wiki_core.paths import WikiPaths


class _LocalReads:
    """Legacy reader; the guarded path supplies an admitted reader instead."""

    def exists(self, path): return path.exists()
    def read_text(self, path, *, errors='strict'): return path.read_text(encoding='utf-8', errors=errors)
    def glob(self, path, pattern): return sorted(path.glob(pattern))
    def markdown(self, path, root): return sorted(wiki_markdown_files(path, wiki_root=root))


def _reads(value):
    return value if value is not None else _LocalReads()

# Minimum number of body bytes (outside the frontmatter) for a .md file not to
# be considered empty/placeholder.
MIN_BODY_BYTES = 40

# Page/memory .md files come from config (cfg.coverage + cfg.paths): each must
# exist, have a non-empty body and frontmatter with page_id. Built per run in
# required_page_files() so localized repos pin their own layout.


def required_page_files(config: WikiConfig) -> dict[str, str]:
    """Repo-relative paths of the required methodology pages, from config."""
    return {
        "source_page": str(config.coverage["methodology_source_page"]),
        "coverage_matrix": str(config.coverage["coverage_matrix_page"]),
        "operation_page": str(config.paths["operation_page"]),
    }


def required_template_files(config: WikiConfig, paths: WikiPaths) -> dict[str, str]:
    """Required wiki templates (filenames from config) under the templates root.

    Besides existing, each must have a real body (the frontmatter may be inside
    a ```yaml block). Check names are keyed by filename so the gate output stays
    meaningful for any localized template set.
    """
    templates_rel = paths.rel(paths.templates_root)
    return {
        f"template:{name}": f"{templates_rel}/{name}"
        for name in config.coverage["required_templates"]
    }

# Scripts/config/core that only need to exist (pipeline support).
REQUIRED_SUPPORT_FILES: dict[str, str] = {
    "config": "wiki.config.yaml",
    "core": "wiki_core/source_manifest.py",
    "manifest_script": "scripts/wiki_extract_source_manifest.py",
    "text_script": "scripts/wiki_extract_text.py",
    "index_script": "scripts/wiki_build_index.py",
    "llm_script": "scripts/wiki_llm_context_pass.py",
    "cache_script": "scripts/wiki_cache_inspect.py",
    "operation_script": "scripts/wiki_operation_compile.py",
}

# Minimum mentions the coverage matrix must contain (case-insensitive). These
# were the sections that used to be missing from the matrix.
# Minimum mentions required in the coverage matrix, per language (config.language).
COVERAGE_REQUIRED_MENTIONS_BY_LANG = {
    "es": ("visibilidad", "agentes", "perceptiva", "karma"),
    "pt": ("visibilidade", "agentes", "perceptiva", "karma"),
    "en": ("visibility", "agents", "perceptive", "karma"),
}
# Accepted markers for the quadrants section (es, pt or en).
QUADRANTS_HEADERS = ("## Cuadrantes", "## Quadrantes", "## Quadrants")


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Returns (yaml_frontmatter_block, body) of a Markdown file.

    Accepts both raw frontmatter at the top of the file (`---` on line 0) and
    frontmatter wrapped in a ```yaml code block (used by some templates). The
    returned body excludes the frontmatter for the byte count.
    """
    lines = text.splitlines()

    # Case 1: raw frontmatter at the top of the file.
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                fm = "\n".join(lines[1:idx])
                body = "\n".join(lines[idx + 1 :])
                return fm, body

    # Case 2: frontmatter inside a ```yaml ... --- ... --- ... ``` block.
    fence_open_re = re.compile(r"^```+\s*ya?ml\s*$", re.IGNORECASE)
    fence_close_re = re.compile(r"^```+\s*$")
    for idx, line in enumerate(lines):
        if fence_open_re.match(line.strip()):
            inner = lines[idx + 1 :]
            if inner and inner[0].strip() == "---":
                for j in range(1, len(inner)):
                    if inner[j].strip() == "---":
                        fm = "\n".join(inner[1:j])
                        # Locate the close of the ```yaml block so the body
                        # includes everything that comes AFTER the block (and not
                        # just the title before it).
                        close = idx + 1 + j + 1
                        while close < len(lines) and not fence_close_re.match(lines[close].strip()):
                            close += 1
                        body = "\n".join(lines[:idx] + lines[close + 1 :])
                        return fm, body
            break

    return None, text


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Minimal frontmatter parse for scalar keys (page_id, page_type...).

    `split_frontmatter` stays local because it also accepts frontmatter wrapped
    in a ```yaml code block (templates); the extracted block is then handed to
    the canonical parser (wiki_core.frontmatter). A simple line-by-line fallback
    survives for template files whose placeholders ({{owner_id}}) are not valid
    YAML.
    """
    fm, _ = split_frontmatter(text)
    if fm is None:
        return {}
    values, _body = canonical_parse_frontmatter(f"---\n{fm}\n---\n")
    if values:
        return values
    # Fallback: only top-level scalar pairs.
    data: dict[str, Any] = {}
    for raw in fm.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")) or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            data[key.strip()] = value
    return data


def body_bytes(text: str) -> int:
    _, body = split_frontmatter(text)
    return len(body.strip().encode("utf-8"))


def check_page_file(name: str, rel: str, reads=None) -> dict[str, Any]:
    reads = _reads(reads)
    path = ROOT / rel
    if not reads.exists(path):
        return {"name": name, "path": rel, "ok": False, "detail": "missing file"}
    text = reads.read_text(path, errors="replace")
    if body_bytes(text) <= MIN_BODY_BYTES:
        return {"name": name, "path": rel, "ok": False, "detail": "empty body/placeholder"}
    fm = parse_frontmatter(text)
    if not fm.get("page_id"):
        return {"name": name, "path": rel, "ok": False, "detail": "frontmatter without page_id"}
    return {"name": name, "path": rel, "ok": True}


def check_template_file(name: str, rel: str, reads=None) -> dict[str, Any]:
    reads = _reads(reads)
    path = ROOT / rel
    if not reads.exists(path):
        return {"name": name, "path": rel, "ok": False, "detail": "missing file"}
    text = reads.read_text(path, errors="replace")
    if body_bytes(text) <= MIN_BODY_BYTES:
        return {"name": name, "path": rel, "ok": False, "detail": "empty body/placeholder"}
    # Templates vary in schema: page templates have page_id; the event template
    # uses event_id; the brief has no page frontmatter. We require real content,
    # not a fixed frontmatter schema.
    return {"name": name, "path": rel, "ok": True}


def check_support_file(name: str, rel: str, reads=None) -> dict[str, Any]:
    reads = _reads(reads)
    path = ROOT / rel
    return {
        "name": name,
        "path": rel,
        "ok": reads.exists(path),
        **({} if reads.exists(path) else {"detail": "missing file"}),
    }


def check_operation_dashboard(rel: str, reads=None) -> dict[str, Any]:
    reads = _reads(reads)
    path = ROOT / rel
    if not reads.exists(path):
        return {"name": "operation_dashboard", "path": rel, "ok": False, "detail": "missing file"}
    fm = parse_frontmatter(reads.read_text(path, errors="replace"))
    if str(fm.get("page_type", "")) != "dashboard":
        return {
            "name": "operation_dashboard",
            "path": rel,
            "ok": False,
            "detail": f"page_type expected `dashboard`, got `{fm.get('page_type')}`",
        }
    if not str(fm.get("purpose", "")).strip():
        return {"name": "operation_dashboard", "path": rel, "ok": False, "detail": "frontmatter without purpose"}
    return {"name": "operation_dashboard", "path": rel, "ok": True}


def check_ingestion_events(paths: WikiPaths, reads=None) -> list[dict[str, Any]]:
    reads = _reads(reads)
    event_dir = paths.ingest_events_dir
    events_rel = paths.rel(event_dir)
    if not reads.exists(event_dir):
        # FAIL LOUD: the configured events directory must exist; a missing
        # target never silently passes the gate.
        return [
            {
                "name": "ingestion_events_dir",
                "path": events_rel,
                "ok": False,
                "detail": "missing events directory",
            }
        ]
    results: list[dict[str, Any]] = []
    for path in reads.glob(event_dir, "*.md"):
        if path.name == "README.md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = reads.read_text(path, errors="replace")
        if any(h in text for h in QUADRANTS_HEADERS):
            results.append({"name": "ingestion_event_quadrants", "path": rel, "ok": True})
        else:
            results.append(
                {
                    "name": "ingestion_event_quadrants",
                    "path": rel,
                    "ok": False,
                    "detail": "quadrants section (`## Quadrantes`/`## Quadrants`) missing",
                }
            )
    if not results:
        results.append(
            {
                "name": "ingestion_events_dir",
                "path": events_rel,
                "ok": False,
                "detail": "no ingestion event found",
            }
        )
    return results


def check_coverage_matrix_sections(rel: str, language: str = "en", reads=None) -> dict[str, Any]:
    reads = _reads(reads)
    path = ROOT / rel
    if not reads.exists(path):
        return {
            "name": "coverage_matrix_sections",
            "path": rel,
            "ok": False,
            "detail": "missing file",
        }
    low = reads.read_text(path, errors="replace").lower()
    mentions = COVERAGE_REQUIRED_MENTIONS_BY_LANG.get(language, COVERAGE_REQUIRED_MENTIONS_BY_LANG["en"])
    missing = [term for term in mentions if term not in low]
    if missing:
        return {
            "name": "coverage_matrix_sections",
            "path": rel,
            "ok": False,
            "detail": "missing mentions: " + ", ".join(missing),
        }
    return {"name": "coverage_matrix_sections", "path": rel, "ok": True}


def discover_source_ids(paths: WikiPaths, reads=None) -> list[str]:
    """Discovers source_ids by scanning the versioned derived manifests."""
    reads = _reads(reads)
    directory = paths.source_manifests
    if not reads.exists(directory):
        return []
    ids: list[str] = []
    for path in reads.glob(directory, "*.json"):
        try:
            data = json.loads(reads.read_text(path))
        except (ValueError, OSError):
            continue
        source_id = data.get("source_id") if isinstance(data, dict) else None
        if isinstance(source_id, str) and source_id:
            ids.append(source_id)
    return ids


# Perceptive layer page types (v5). The coverage requires real USE: at least
# one real journal and at least one real map/infographic (not template).
PERCEPTIVE_JOURNAL_TYPES = {"journal_entry"}
PERCEPTIVE_MAP_TYPES = {"relationship_map", "infographic", "moodboard", "media_capture"}
PERCEPTIVE_TYPES = PERCEPTIVE_JOURNAL_TYPES | PERCEPTIVE_MAP_TYPES


def _real_perceptive_pages(paths: WikiPaths, reads=None) -> list[dict[str, Any]]:
    """REAL perceptive pages under the memory root: perceptive page_type, status
    not 'template', non-empty body and `perception_policy` marker in the frontmatter."""
    reads = _reads(reads)
    memory_root = paths.memory_root
    pages: list[dict[str, Any]] = []
    if not reads.exists(memory_root):
        return pages
    for path in reads.markdown(memory_root, paths.root):
        text = reads.read_text(path, errors="replace")
        fm = parse_frontmatter(text)
        page_type = str(fm.get("page_type", ""))
        if page_type not in PERCEPTIVE_TYPES:
            continue
        if str(fm.get("status", "")).strip().lower() == "template":
            continue
        if "perception_policy" not in text:
            continue
        if body_bytes(text) <= MIN_BODY_BYTES:
            continue
        pages.append({"rel": paths.rel(path), "page_type": page_type})
    return pages


def check_perceptive_usage(paths: WikiPaths, reads=None) -> list[dict[str, Any]]:
    """Requires real USE of the perceptive layer, not just the presence of templates:
    at least one real journal and at least one real map/infographic."""
    pages = _real_perceptive_pages(paths, reads)
    journals = [p for p in pages if p["page_type"] in PERCEPTIVE_JOURNAL_TYPES]
    maps = [p for p in pages if p["page_type"] in PERCEPTIVE_MAP_TYPES]
    fallback = f"{paths.config.paths['memory_root']}/**"
    results = [
        {
            "name": "perceptive_journal_real",
            "path": journals[0]["rel"] if journals else fallback,
            "ok": bool(journals),
            **({} if journals else {"detail": "no real journal (page_type=journal_entry, status!=template) found"}),
        },
        {
            "name": "perceptive_map_real",
            "path": maps[0]["rel"] if maps else fallback,
            "ok": bool(maps),
            **({} if maps else {"detail": "no real map/infographic found"}),
        },
    ]
    return results


def check_llm_context_pass(paths: WikiPaths, config: WikiConfig, reads=None) -> list[dict[str, Any]]:
    """Portable LLM pass gate.

    For each `*-llm-context-request.json` file present in extraction-events, if
    `required_context_pass` is true and some chunk has a cache_key without a
    result in `llm-cache/<cache_key>.json`, reports failure. If there are no
    request files, does NOT fail (clean environment/CI). The existence of a
    `-llm-context-plan.json` file NEVER counts as proof of a pass.
    """
    guarded = reads is not None
    reads = _reads(reads)
    if not config.llm.get("required_context_pass", True):
        return []
    req_dir = paths.extraction_events
    cache_dir = paths.llm_cache
    if not reads.exists(req_dir):
        return []
    requests = reads.glob(req_dir, "*-llm-context-request.json")
    if not requests:
        return []
    results: list[dict[str, Any]] = []
    for path in requests:
        rel = path.relative_to(ROOT).as_posix()
        try:
            if re.fullmatch(r'folder-[0-9a-f]{64}-[0-9a-f]{64}-llm-context-request\.json', path.name):
                from wiki_core.llm.context_pass import load_local_request
                data = load_local_request(paths, path, read_bytes=reads.read_bytes if guarded else None)
            else:
                data = json.loads(reads.read_text(path))
        except (ValueError, OSError):
            results.append(
                {
                    "name": "llm_context_pending",
                    "path": rel,
                    "ok": False,
                    "detail": "unreadable request file",
                }
            )
            continue
        chunks = data.get("chunks", []) if isinstance(data, dict) else []
        from wiki_core.llm.context_pass import is_local_folder_request
        try:
            pending = [
                chunk for chunk in chunks
                if read_matching_result(cache_dir, data, chunk,
                    root=ROOT if is_local_folder_request(data) else None,
                    read_text=reads.read_text if guarded else None) is None
            ]
        except (ValueError, OSError):
            results.append({'name': 'llm_context_pending', 'path': rel, 'ok': False,
                            'detail': 'local result cache unavailable or unsafe'})
            continue
        if pending:
            results.append(
                {
                    "name": "llm_context_pending",
                    "path": rel,
                    "ok": False,
                    "detail": f"{len(pending)} chunk(s) without result in llm-cache",
                }
            )
        else:
            results.append({"name": "llm_context_pending", "path": rel, "ok": True})
    return results


def run_checks(root: Path | None = None, *, reads=None, config=None) -> dict[str, Any]:
    global ROOT
    if root is not None:
        ROOT = root
    if config is None:
        config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)

    checks: list[dict[str, Any]] = []

    page_files = required_page_files(config)
    for name, rel in page_files.items():
        checks.append(check_page_file(name, rel, reads))
    for name, rel in required_template_files(config, paths).items():
        checks.append(check_template_file(name, rel, reads))
    for name, rel in REQUIRED_SUPPORT_FILES.items():
        checks.append(check_support_file(name, rel, reads))

    checks.append(check_operation_dashboard(page_files["operation_page"], reads))
    checks.extend(check_ingestion_events(paths, reads))
    checks.append(check_coverage_matrix_sections(page_files["coverage_matrix"], config.language, reads))
    checks.extend(check_perceptive_usage(paths, reads))

    # Discovered derived artifacts (no absolute path): we only report the
    # discovery for diagnostics, without failing for the absence of a specific
    # source (the environment may be clean).
    # Informational: the derived manifests are gitignored, so a clean clone/CI
    # does not have them. We do not fail for absence; we just report the discovery.
    source_ids = discover_source_ids(paths, reads)
    checks.append(
        {
            "name": "source_manifests_present",
            "path": paths.rel(paths.source_manifests),
            "ok": True,
            "detail": f"{len(source_ids)} manifest(s) discovered" + ("" if source_ids else " (empty on clean clone/CI)"),
        }
    )

    checks.extend(check_llm_context_pass(paths, config, reads))

    errors = [check for check in checks if not check["ok"]]
    return {"checks": checks, "errors": errors, "complete": not errors}


class _SelectedReads:
    """The check can consume only in-memory bytes admitted as one selection."""
    def __init__(self, root, physical, contents):
        self.root, self.files, self.directories, self.contents = Path(root), physical['files'], physical['directories'], contents

    def _rel(self, path):
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            raise RuntimeError('methodology selection unavailable') from None

    def exists(self, path):
        rel = self._rel(path)
        return rel == '.' or rel in self.files or rel in self.directories

    def read_bytes(self, path):
        rel = self._rel(path)
        if rel not in self.contents:
            raise RuntimeError('methodology body outside admitted selection')
        return self.contents[rel]

    def read_text(self, path, *, errors='strict'):
        return self.read_bytes(path).decode('utf-8', errors=errors)

    def glob(self, path, pattern):
        rel = self._rel(path)
        prefix = '' if rel == '.' else rel + '/'
        return [self.root / name for name in sorted(self.files)
                if name.startswith(prefix) and '/' not in name[len(prefix):]
                and fnmatch.fnmatchcase(name[len(prefix):], pattern)]

    def markdown(self, path, root):
        from wiki_core.traversal import is_protected_artifact
        rel = self._rel(path)
        prefix = '' if rel == '.' else rel + '/'
        return [self.root / name for name in sorted(self.files)
                if name.startswith(prefix) and name.endswith('.md')
                and not is_protected_artifact(Path(name))]


def methodology_selection(root, binding, *, context_id, approved_revision, base, head,
                          branch, normative_paths):
    """The host must admit bootstrap before calling; other bodies stay unopened."""
    from wiki_core.audit_r1_inventory import inventory, select, _worktree_bytes
    from wiki_core.context_policy import PolicyError, git_file, safe_path, within
    from wiki_core.traversal import is_protected_artifact
    root = Path(root).resolve(strict=True)
    snapshot = inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                         base=base, head=head, branch=branch, normative_paths=normative_paths)
    # Config is an explicitly host-admitted bootstrap read, never candidate authority.
    approved_config = git_file(root, approved_revision, 'wiki.config.yaml')
    config_meta = snapshot['physical']['files'].get('wiki.config.yaml')
    if config_meta is None or config_meta['size'] > 2_000_000:
        raise PolicyError('methodology working configuration unavailable')
    if _worktree_bytes(root, {'path': 'wiki.config.yaml', **config_meta}) != approved_config:
        raise PolicyError('methodology working configuration differs from approved')
    try:
        config = config_from_mapping(yaml.safe_load(approved_config.decode('utf-8')))
    except (UnicodeError, yaml.YAMLError, ValueError, TypeError, KeyError):
        raise PolicyError('methodology approved configuration unavailable') from None
    paths = WikiPaths(root, config)
    def rel(path):
        try: return safe_path(path.relative_to(root).as_posix(), allow_root=True)
        except (TypeError, ValueError) as exc: raise PolicyError('methodology path unavailable') from exc
    required = {safe_path(item) for item in set(required_page_files(config).values()) |
                set(required_template_files(config, paths).values())}
    support = {safe_path(item) for item in REQUIRED_SUPPORT_FILES.values()}
    files, directories = snapshot['physical']['files'], snapshot['physical']['directories']
    if not (required | support) <= files.keys():
        raise PolicyError('methodology required input unavailable')
    memory, events = rel(paths.memory_root), rel(paths.ingest_events_dir)
    manifests, requests, caches = rel(paths.source_manifests), rel(paths.extraction_events), rel(paths.llm_cache)
    request_names = {name for name in files if str(Path(name).parent) == requests
                     and fnmatch.fnmatchcase(Path(name).name, '*-llm-context-request.json')}
    def candidate(name):
        parent = str(Path(name).parent)
        if within(name, memory) and name.endswith('.md') and not is_protected_artifact(Path(name)):
            return True
        if parent == events and name.endswith('.md') and Path(name).name != 'README.md': return True
        if parent == manifests and name.endswith('.json'): return True
        if (config.llm.get('required_context_pass', True) and parent == requests
                and fnmatch.fnmatchcase(Path(name).name, '*-llm-context-request.json')): return True
        return bool(config.llm.get('required_context_pass', True) and request_names
                and parent in (caches, caches + '/local-folder')
                and re.fullmatch(r'[0-9a-f]{64}\.json', Path(name).name))
    # A tracked eligible input missing from the worktree is not evidence that
    # the check's universe is complete. Do not silently treat it as absent.
    if any(candidate(name) for name in snapshot['missing_tracked']):
        raise PolicyError('methodology tracked input unavailable')
    selected = set(required) | {name for name in files if candidate(name)}
    for name in directories:
        parent, leaf = str(Path(name).parent), Path(name).name
        if ((parent == events and leaf.endswith('.md') and leaf != 'README.md')
                or (parent == manifests and leaf.endswith('.json'))
                or (config.llm.get('required_context_pass', True) and parent == requests
                    and fnmatch.fnmatchcase(leaf, '*-llm-context-request.json'))
                or (config.llm.get('required_context_pass', True) and request_names
                    and parent in (caches, caches + '/local-folder')
                    and re.fullmatch(r'[0-9a-f]{64}\.json', leaf))):
            raise PolicyError('methodology input type unavailable')
    request = [{'kind': 'worktree', 'path': name} for name in sorted(selected)]
    selection = select(snapshot, request)
    return snapshot, selection, config, approved_config


def guarded_methodology(root, binding, *, context_id, approved_revision, base, head, branch,
                        normative_paths, inventory_sha256, selection_sha256, admit):
    """Run only after external bootstrap/whole-selection admission and isolation."""
    import copy
    from wiki_core.audit_r1_inventory import _worktree_bytes
    from wiki_core.context_policy import PolicyError
    if not callable(admit): raise PolicyError('methodology admission unavailable')
    args = dict(context_id=context_id, approved_revision=approved_revision, base=base,
                head=head, branch=branch, normative_paths=normative_paths)
    snapshot, selection, config, approved_config = methodology_selection(root, binding, **args)
    if (snapshot['inventory_sha256'] != inventory_sha256 or
            selection['selection_sha256'] != selection_sha256):
        raise PolicyError('methodology selection changed')
    if admit(copy.deepcopy(selection)) is not True: raise PolicyError('methodology admission unavailable')
    root = Path(root).resolve(strict=True)
    if sum(item['size'] for item in selection['inputs']) > 8_000_000 or any(item['size'] > 2_000_000 for item in selection['inputs']):
        raise PolicyError('methodology selection budget exceeded')
    contents = {}
    attempted = 0
    try:
        current, selected, _, current_config = methodology_selection(root, binding, **args)
        if (current['inventory_sha256'] != inventory_sha256 or
                selected['selection_sha256'] != selection_sha256 or current_config != approved_config):
            raise PolicyError('methodology selection changed')
        for item in selection['inputs']:
            if admit(copy.deepcopy(selection)) is not True: raise PolicyError('methodology admission changed')
            attempted += 1
            contents[item['path']] = _worktree_bytes(root, item)
        if admit(copy.deepcopy(selection)) is not True: raise PolicyError('methodology admission changed')
        current, selected, _, current_config = methodology_selection(root, binding, **args)
        if (current['inventory_sha256'] != inventory_sha256 or
                selected['selection_sha256'] != selection_sha256 or current_config != approved_config):
            raise PolicyError('methodology selection changed')
        result = run_checks(root, reads=_SelectedReads(root, snapshot['physical'], contents), config=config)
    except Exception:
        return {'state': 'partial', 'scope': 'methodology_only', 'selection_sha256': selection_sha256,
                'source_bodies_validated': len(contents),
                'source_body_attempts_may_have_read_bytes': attempted,
                'bootstrap_may_overlap_selection': True,
                'global_audit': 'not_performed', 'host_admission': 'external_not_verified',
                'live_observation': 'not_verified', 'bootstrap': 'external_not_verified'}
    return {'state': 'failed' if result['errors'] else 'completed', 'scope': 'methodology_only',
            'selection_sha256': selection_sha256, 'result': result, 'source_bodies_validated': len(contents),
            'source_body_attempts_may_have_read_bytes': attempted,
            'ignored_selected': len(set(contents) & set(snapshot['ignored'])),
            'readset': [{'path': path, 'size': len(contents[path]),
                         'sha256': hashlib.sha256(contents[path]).hexdigest()} for path in sorted(contents)],
            'bootstrap_may_overlap_selection': True, 'global_audit': 'not_performed',
            'host_admission': 'external_not_verified', 'live_observation': 'not_verified',
            'bootstrap': 'external_not_verified'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="returns code != 0 if any check has ok=false")
    parser.add_argument('--context-guard', help='explicit owner context; host admission remains external')
    parser.add_argument('--context-policy-revision', help='approved full Git revision')
    parser.add_argument('--context-base', help='approved base full Git revision')
    parser.add_argument('--context-head', help='candidate head full Git revision')
    parser.add_argument('--context-branch', help='candidate wiki branch')
    parser.add_argument('--context-normative', action='append', default=[], help='host-declared normative path; include wiki.config.yaml')
    parser.add_argument('--context-inventory-sha256', help='externally admitted inventory digest')
    parser.add_argument('--context-selection-sha256', help='externally admitted selection digest')
    parser.add_argument('--context-plan', action='store_true', help='prepare a metadata selection, not a check')
    args = parser.parse_args()
    options = (args.context_guard, args.context_policy_revision, args.context_base, args.context_head,
               args.context_branch, args.context_normative, args.context_inventory_sha256,
               args.context_selection_sha256, args.context_plan)
    if any(options):
        if (not args.check or not all((args.context_guard, args.context_policy_revision, args.context_base,
                                      args.context_head, args.context_branch, args.context_normative))):
            parser.error('context guard requires --check, revisions, branch and normative paths')
        if args.context_plan and (args.context_inventory_sha256 or args.context_selection_sha256):
            parser.error('context plan does not accept admitted digests')
        if not args.context_plan and not all((args.context_inventory_sha256, args.context_selection_sha256)):
            parser.error('context execution requires externally admitted inventory and selection digests')
        from wiki_core.coordination_context import CoordinationBinding
        try:
            binding = CoordinationBinding.from_environment()
            params = dict(context_id=args.context_guard, approved_revision=args.context_policy_revision,
                          base=args.context_base, head=args.context_head, branch=args.context_branch,
                          normative_paths=args.context_normative)
            if args.context_plan:
                snapshot, selection, _, _ = methodology_selection(ROOT, binding, **params)
                output = {'state': 'selection_only', 'scope': 'methodology_only',
                          'inventory_sha256': snapshot['inventory_sha256'], 'selection': selection,
                          'bootstrap': 'external_not_verified', 'global_audit': 'not_performed'}
                print(json.dumps(output, ensure_ascii=False, indent=2))
                return 0
            # As in the existing context-bound secrets CLI, the host must
            # independently admit this exact selection. A matching digest binds
            # those bytes but does not authenticate that admission or actor.
            output = guarded_methodology(ROOT, binding, **params,
                inventory_sha256=args.context_inventory_sha256, selection_sha256=args.context_selection_sha256,
                admit=lambda selection: selection['selection_sha256'] == args.context_selection_sha256)
        except (ValueError, OSError, RuntimeError, TypeError, KeyError):
            print(json.dumps({'state': 'refused', 'scope': 'methodology_only',
                              'global_audit': 'not_performed', 'bootstrap': 'external_not_verified'}))
            return 1
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output['state'] == 'completed' else 1
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.check and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
