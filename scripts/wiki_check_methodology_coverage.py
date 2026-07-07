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
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config
from wiki_core.frontmatter import parse_frontmatter as canonical_parse_frontmatter
from wiki_core.paths import WikiPaths

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
    "pt": ("visibilidade", "agentes", "perceptiva", "karma"),
    "en": ("visibility", "agents", "perceptive", "karma"),
}
# Accepted markers for the quadrants section (pt or en).
QUADRANTS_HEADERS = ("## Quadrantes", "## Quadrants")


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


def check_page_file(name: str, rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.exists():
        return {"name": name, "path": rel, "ok": False, "detail": "missing file"}
    text = path.read_text(encoding="utf-8", errors="replace")
    if body_bytes(text) <= MIN_BODY_BYTES:
        return {"name": name, "path": rel, "ok": False, "detail": "empty body/placeholder"}
    fm = parse_frontmatter(text)
    if not fm.get("page_id"):
        return {"name": name, "path": rel, "ok": False, "detail": "frontmatter without page_id"}
    return {"name": name, "path": rel, "ok": True}


def check_template_file(name: str, rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.exists():
        return {"name": name, "path": rel, "ok": False, "detail": "missing file"}
    text = path.read_text(encoding="utf-8", errors="replace")
    if body_bytes(text) <= MIN_BODY_BYTES:
        return {"name": name, "path": rel, "ok": False, "detail": "empty body/placeholder"}
    # Templates vary in schema: page templates have page_id; the event template
    # uses event_id; the brief has no page frontmatter. We require real content,
    # not a fixed frontmatter schema.
    return {"name": name, "path": rel, "ok": True}


def check_support_file(name: str, rel: str) -> dict[str, Any]:
    path = ROOT / rel
    return {
        "name": name,
        "path": rel,
        "ok": path.exists(),
        **({} if path.exists() else {"detail": "missing file"}),
    }


def check_operation_dashboard(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.exists():
        return {"name": "operation_dashboard", "path": rel, "ok": False, "detail": "missing file"}
    fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
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


def check_ingestion_events(paths: WikiPaths) -> list[dict[str, Any]]:
    event_dir = paths.ingest_events_dir
    events_rel = paths.rel(event_dir)
    if not event_dir.exists():
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
    for path in sorted(event_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
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


def check_coverage_matrix_sections(rel: str, language: str = "en") -> dict[str, Any]:
    path = ROOT / rel
    if not path.exists():
        return {
            "name": "coverage_matrix_sections",
            "path": rel,
            "ok": False,
            "detail": "missing file",
        }
    low = path.read_text(encoding="utf-8", errors="replace").lower()
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


def discover_source_ids(paths: WikiPaths) -> list[str]:
    """Discovers source_ids by scanning the versioned derived manifests."""
    directory = paths.source_manifests
    if not directory.exists():
        return []
    ids: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
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


def _real_perceptive_pages(paths: WikiPaths) -> list[dict[str, Any]]:
    """REAL perceptive pages under the memory root: perceptive page_type, status
    not 'template', non-empty body and `perception_policy` marker in the frontmatter."""
    memory_root = paths.memory_root
    pages: list[dict[str, Any]] = []
    if not memory_root.exists():
        return pages
    for path in sorted(memory_root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
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


def check_perceptive_usage(paths: WikiPaths) -> list[dict[str, Any]]:
    """Requires real USE of the perceptive layer, not just the presence of templates:
    at least one real journal and at least one real map/infographic."""
    pages = _real_perceptive_pages(paths)
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


def check_llm_context_pass(paths: WikiPaths, config: WikiConfig) -> list[dict[str, Any]]:
    """Portable LLM pass gate.

    For each `*-llm-context-request.json` file present in extraction-events, if
    `required_context_pass` is true and some chunk has a cache_key without a
    result in `llm-cache/<cache_key>.json`, reports failure. If there are no
    request files, does NOT fail (clean environment/CI). The existence of a
    `-llm-context-plan.json` file NEVER counts as proof of a pass.
    """
    if not config.llm.get("required_context_pass", True):
        return []
    req_dir = paths.extraction_events
    cache_dir = paths.llm_cache
    if not req_dir.exists():
        return []
    requests = sorted(req_dir.glob("*-llm-context-request.json"))
    if not requests:
        return []
    results: list[dict[str, Any]] = []
    for path in requests:
        rel = path.relative_to(ROOT).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
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
        pending = [
            chunk
            for chunk in chunks
            if not (cache_dir / f"{chunk.get('cache_key')}.json").exists()
        ]
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


def run_checks(root: Path | None = None) -> dict[str, Any]:
    global ROOT
    if root is not None:
        ROOT = root
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)

    checks: list[dict[str, Any]] = []

    page_files = required_page_files(config)
    for name, rel in page_files.items():
        checks.append(check_page_file(name, rel))
    for name, rel in required_template_files(config, paths).items():
        checks.append(check_template_file(name, rel))
    for name, rel in REQUIRED_SUPPORT_FILES.items():
        checks.append(check_support_file(name, rel))

    checks.append(check_operation_dashboard(page_files["operation_page"]))
    checks.extend(check_ingestion_events(paths))
    checks.append(check_coverage_matrix_sections(page_files["coverage_matrix"], config.language))
    checks.extend(check_perceptive_usage(paths))

    # Discovered derived artifacts (no absolute path): we only report the
    # discovery for diagnostics, without failing for the absence of a specific
    # source (the environment may be clean).
    # Informational: the derived manifests are gitignored, so a clean clone/CI
    # does not have them. We do not fail for absence; we just report the discovery.
    source_ids = discover_source_ids(paths)
    checks.append(
        {
            "name": "source_manifests_present",
            "path": paths.rel(paths.source_manifests),
            "ok": True,
            "detail": f"{len(source_ids)} manifest(s) discovered" + ("" if source_ids else " (empty on clean clone/CI)"),
        }
    )

    checks.extend(check_llm_context_pass(paths, config))

    errors = [check for check in checks if not check["ok"]]
    return {"checks": checks, "errors": errors, "complete": not errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="returns code != 0 if any check has ok=false")
    args = parser.parse_args()
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.check and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
