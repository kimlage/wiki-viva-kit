#!/usr/bin/env python3
"""Summarize the current wiki PR diff."""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config

CONFIG = load_config(ROOT)
_MEMORY_ROOT = CONFIG.paths["memory_root"]
_REFERENCES_ROOT = CONFIG.paths["references_root"]
_SYSTEM_DIRNAME = CONFIG.paths["system_dirname"]

# Untracked generated docs to skip. SUPERSET of en + pt prefixes so one shared
# codebase serves both layouts (compatibility for localized repos).
IGNORED_UNTRACKED_PREFIXES = ("docs/memories/", "docs/memorias/")

# Category labels for the generated summary (user-facing text): one string
# table per language, identical keys, selected by config.language.
STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "holons": "holons",
        "people": "pessoas",
        "governance": "governanca",
        "projects": "projetos",
        "sources": "fontes",
        "epistemology_actions": "epistemologia-acoes",
        "timelines": "timelines",
        "evidence": "evidencias",
        "coverage": "cobertura",
        "references": "referencias",
        "scripts": "scripts",
        "github": "github",
        "other": "outros",
    },
    "en": {
        "holons": "holons",
        "people": "people",
        "governance": "governance",
        "projects": "projects",
        "sources": "sources",
        "epistemology_actions": "epistemology-actions",
        "timelines": "timelines",
        "evidence": "evidence",
        "coverage": "coverage",
        "references": "references",
        "scripts": "scripts",
        "github": "github",
        "other": "others",
    },
}

# Directory name (single segment under the memory root) -> summary category.
# SUPERSET of en + pt directory names: compatibility for localized repos that
# pin a translated layout (same table style as the auditor's ontology map).
CONTEXT_CATEGORY_BY_DIR: dict[str, str] = {
    "holons": "holons",
    "people": "people",
    "pessoas": "people",
    "roles": "governance",
    "papeis": "governance",
    "responsibilities": "governance",
    "responsabilidades": "governance",
    "assignments": "governance",
    "atribuicoes": "governance",
    "projects": "projects",
    "projetos": "projects",
    "initiatives": "projects",
    "iniciativas": "projects",
    "sources": "sources",
    "fontes": "sources",
    "claims": "epistemology_actions",
    "decisions": "epistemology_actions",
    "decisoes": "epistemology_actions",
    "insights": "epistemology_actions",
    "actions": "epistemology_actions",
    "acoes": "epistemology_actions",
    "timelines": "timelines",
    "evidence": "evidence",
    "evidencias": "evidence",
    "coverage": "coverage",
    "cobertura": "coverage",
}

# Directory name (single segment under the memory root) -> entity type. Entity
# ids are stable English identifiers (not localized output). SUPERSET of en +
# pt directory names: compatibility for localized repos.
ENTITY_BY_DIR: dict[str, str] = {
    "ontology": "ontology",
    "ontologia": "ontology",
    "people": "person",
    "pessoas": "person",
    "holons": "holon",
    "roles": "role",
    "papeis": "role",
    "responsibilities": "responsibility",
    "responsabilidades": "responsibility",
    "assignments": "assignment",
    "atribuicoes": "assignment",
    "projects": "project",
    "projetos": "project",
    "initiatives": "initiative",
    "iniciativas": "initiative",
    "sources": "source",
    "fontes": "source",
    "claims": "claim",
    "decisions": "decision",
    "decisoes": "decision",
    "insights": "insight",
    "actions": "action",
    "acoes": "action",
    "timelines": "timeline",
    "evidence": "evidence",
    "evidencias": "evidence",
    "coverage": "coverage",
    "cobertura": "coverage",
}


def _label(key: str) -> str:
    table = STRINGS.get(CONFIG.language, STRINGS["en"])
    return table[key]


def git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        return ""


def diff_name_status() -> list[tuple[str, str]]:
    rows: dict[str, str] = {}
    for args in (
        ["diff", "--name-status", "main...HEAD"],
        ["diff", "--name-status"],
        ["diff", "--cached", "--name-status"],
    ):
        output = git(args)
        for line in output.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            status = parts[0]
            path = parts[-1] if status.startswith(("R", "C")) else parts[1]
            rows[path] = status
    untracked = git(["ls-files", "--others", "--exclude-standard"])
    for path in untracked.splitlines():
        if path and not path.startswith(IGNORED_UNTRACKED_PREFIXES):
            rows.setdefault(path, "A")
    return sorted((status, path) for path, status in rows.items())


def _memory_segment(path: str) -> str | None:
    """First directory segment of ``path`` under the memory root, if any."""
    prefix = f"{_MEMORY_ROOT}/"
    if not path.startswith(prefix):
        return None
    return path[len(prefix):].split("/", 1)[0]


def context_for(path: str) -> str:
    segment = _memory_segment(path)
    if segment is not None:
        if segment in CONFIG.contexts:
            return segment
        if segment == _SYSTEM_DIRNAME:
            return _SYSTEM_DIRNAME
        category = CONTEXT_CATEGORY_BY_DIR.get(segment)
        if category is not None:
            return _label(category)
        return _label("other")
    if path.startswith(f"{_REFERENCES_ROOT}/"):
        return _label("references")
    if path.startswith("scripts/"):
        return _label("scripts")
    if path.startswith(".github/"):
        return _label("github")
    return _label("other")


def entity_for(path: str) -> str:
    segment = _memory_segment(path)
    if segment is not None:
        return ENTITY_BY_DIR.get(segment, "context-memory")
    if path.startswith(f"{_REFERENCES_ROOT}/templates/wiki/"):
        return "wiki-template"
    if path.startswith("scripts/"):
        return "script"
    if path.startswith(".github/"):
        return "github"
    return "other"


def main() -> int:
    rows = diff_name_status()
    grouped: dict[str, list[str]] = defaultdict(list)
    by_entity: dict[str, list[str]] = defaultdict(list)
    for status, path in rows:
        grouped[context_for(path)].append(f"- `{status}` `{path}`")
        by_entity[entity_for(path)].append(f"- `{status}` `{path}`")

    print("# Wiki PR Summary")
    print()
    if not rows:
        print("No diff detected against main or working tree.")
        return 0
    print("## Changed files by context")
    print()
    for context in sorted(grouped):
        print(f"### {context}")
        print()
        print("\n".join(grouped[context]))
        print()
    print("## Changed files by entity type")
    print()
    for entity in sorted(by_entity):
        print(f"### {entity}")
        print()
        print("\n".join(by_entity[entity]))
        print()
    print("## Privacy review hints")
    print()
    # Context-driven (no personal context hardcoded in the shared kit).
    for ctx in CONFIG.contexts:
        print(f"- Review any `{_MEMORY_ROOT}/{ctx}` changes for sensitive detail.")
    print("- Confirm `docs/` changes are references/templates/snapshots, not live memory.")
    print()
    print("## Validation checklist")
    print()
    print("- [ ] `python3 scripts/wiki_audit.py --check`")
    print("- [ ] `git diff --check`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
