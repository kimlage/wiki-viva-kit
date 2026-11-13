#!/usr/bin/env python3
"""Summarize a wiki proposal against a selected local Git base.

By default, prefer the local ``origin/main`` tracking ref, then local ``main``
with a warning. ``--base`` selects an explicit commit or ref. No fetch is
performed: an operator must verify that the selected base is current and is
the intended PR base. This report is neither an approval nor authorization.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import defaultdict

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.git_env import local_git_environment, local_git_executable

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
    "es": {
        "holons": "holones",
        "people": "personas",
        "governance": "gobernanza",
        "projects": "proyectos",
        "sources": "fuentes",
        "epistemology_actions": "epistemologia-acciones",
        "timelines": "lineas-de-tiempo",
        "evidence": "evidencias",
        "coverage": "cobertura",
        "references": "referencias",
        "scripts": "scripts",
        "github": "github",
        "other": "otros",
    },
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


class SummaryError(ValueError):
    """The summary cannot be derived without a reliable local Git view."""


def _git(args: list[str], *, missing_ref_ok: bool = False) -> bytes | None:
    try:
        result = subprocess.run(
            [local_git_executable(), "--no-lazy-fetch", *args], cwd=ROOT,
            env=local_git_environment(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError) as exc:
        raise SummaryError("Git is unavailable") from exc
    if result.returncode:
        if missing_ref_ok and result.returncode == 1:
            return None
        raise SummaryError("Git comparison or revision verification failed")
    return result.stdout


def git(args: list[str]) -> str:
    """Run a local Git command; failures cannot masquerade as an empty diff."""
    result = _git(args)
    assert result is not None
    return os.fsdecode(result).strip()


def _optional_ref(ref: str) -> str | None:
    exists = _git(["show-ref", "--verify", "--quiet", ref], missing_ref_ok=True)
    return None if exists is None else _resolve_commit(ref)


def _resolve_commit(ref: str) -> str:
    if not isinstance(ref, str) or not ref or ref.startswith("-") or any(ord(c) < 32 for c in ref):
        raise SummaryError("invalid base or revision")
    result = git(["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"])
    if len(result) not in (40, 64) or any(c not in "0123456789abcdef" for c in result):
        raise SummaryError("invalid Git commit")
    return result


def _select_base(base: str | None) -> tuple[str, str, str, str, str | None, str | None]:
    """Resolve the selected and reference commits without fetching or guessing trust."""
    origin = _optional_ref("refs/remotes/origin/main")
    local = _optional_ref("refs/heads/main")
    if base is not None:
        label = base
        selected = _resolve_commit(base)
    elif origin is not None:
        label, selected = "refs/remotes/origin/main", origin
    elif local is not None:
        label, selected = "refs/heads/main", local
    else:
        raise SummaryError("no base found; pass --base with an existing commit or ref")
    head = _resolve_commit("HEAD")
    merge_bases = git(["merge-base", "--all", selected, head]).splitlines()
    if len(merge_bases) != 1:
        raise SummaryError("a unique merge base is unavailable")
    return label, selected, head, merge_bases[0], origin, local


def _name_status(args: list[str]) -> list[tuple[str, str]]:
    # Report a move as deletion plus addition so both privacy contexts are
    # visible, including when Git's rename detection would select only one.
    raw = _git(["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-status", "-z", *args])
    assert raw is not None
    parts = raw.split(b"\0")
    if parts[-1] != b"":
        raise SummaryError("Git returned an incomplete diff")
    parts.pop()
    result: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        status = os.fsdecode(parts[index])
        index += 1
        if not status or index >= len(parts):
            raise SummaryError("Git returned an invalid diff")
        path = os.fsdecode(parts[index])
        index += 1
        if status.startswith(("R", "C")):
            raise SummaryError("Git returned an unexpected rename or copy status")
        result.append((status, path))
    return result


def diff_name_status(base: str | None = None) -> list[tuple[str, str]]:
    """Return the committed, unstaged, staged and untracked path union."""
    label, selected, head, _, origin, local = _select_base(base)
    return _diff_name_status(label, selected, head, origin, local)


def _diff_name_status(label: str, selected: str, head: str,
                      origin: str | None, local: str | None) -> list[tuple[str, str]]:
    rows: dict[str, list[str]] = {}

    def record(path: str, status: str) -> None:
        statuses = rows.setdefault(path, [])
        if status not in statuses:
            statuses.append(status)

    for args in (
        [f"{selected}...{head}"],
        [],
        ["--cached"],
    ):
        for status, path in _name_status(args):
            record(path, status)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "-z"])
    assert untracked is not None
    if untracked and not untracked.endswith(b"\0"):
        raise SummaryError("Git returned an incomplete untracked list")
    for raw_path in untracked.split(b"\0"):
        path = os.fsdecode(raw_path)
        if path and not path.startswith(IGNORED_UNTRACKED_PREFIXES):
            record(path, "A")
    if (_resolve_commit("HEAD") != head or _resolve_commit(label) != selected
            or _optional_ref("refs/remotes/origin/main") != origin
            or _optional_ref("refs/heads/main") != local):
        raise SummaryError("Git base or head changed during summary; retry")
    return sorted(("/".join(statuses), path) for path, statuses in rows.items())


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="explicit local base ref or commit; no fetch is performed")
    args = parser.parse_args(argv)
    try:
        label, selected, head, merge_base, origin, local = _select_base(args.base)
        rows = _diff_name_status(label, selected, head, origin, local)
    except SummaryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    grouped: dict[str, list[str]] = defaultdict(list)
    by_entity: dict[str, list[str]] = defaultdict(list)
    for status, path in rows:
        grouped[context_for(path)].append(f"- `{status}` `{path}`")
        by_entity[entity_for(path)].append(f"- `{status}` `{path}`")

    print("# Wiki PR Summary")
    print()
    print(f"Base: `{label}` at `{selected}`; merge-base: `{merge_base}`; head: `{head}`.")
    print("No fetch was performed; verify that this is the intended current PR base.")
    if args.base is None and label == "refs/heads/main":
        print("WARNING: origin/main is unavailable; using local main.")
    elif origin is None:
        print("WARNING: origin/main is unavailable; the selected base cannot be compared to it.")
    if origin is not None and local is not None and origin != local:
        print(f"WARNING: local main `{local}` differs from origin/main `{origin}`.")
    if origin is not None and selected != origin:
        print(f"WARNING: selected base differs from origin/main `{origin}`.")
    if merge_base != selected:
        print("WARNING: selected base is not an ancestor of HEAD; committed changes use the merge-base.")
    print()
    if not rows:
        print("No diff detected against the merge-base or working tree.")
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
