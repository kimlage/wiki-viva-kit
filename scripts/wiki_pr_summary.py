#!/usr/bin/env python3
"""Summarize the current wiki PR diff."""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_UNTRACKED_PREFIXES = ("docs/memorias/",)


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


def context_for(path: str) -> str:
    if path.startswith("memorias/financeiro/"):
        return "financeiro"
    if path.startswith("memorias/documentos/"):
        return "documentos"
    if path.startswith("memorias/profissional/"):
        return "profissional"
    if path.startswith("memorias/empresas/"):
        return "empresas"
    if path.startswith("memorias/projetos-pessoais/"):
        return "projetos-pessoais"
    if path.startswith("memorias/sistema/"):
        return "sistema"
    if path.startswith("memorias/holons/"):
        return "holons"
    if path.startswith("memorias/pessoas/"):
        return "pessoas"
    if path.startswith("memorias/papeis/") or path.startswith("memorias/responsabilidades/") or path.startswith("memorias/atribuicoes/"):
        return "governanca"
    if path.startswith("memorias/projetos/") or path.startswith("memorias/iniciativas/"):
        return "projetos"
    if path.startswith("memorias/fontes/"):
        return "fontes"
    if path.startswith("memorias/claims/") or path.startswith("memorias/decisoes/") or path.startswith("memorias/insights/") or path.startswith("memorias/acoes/"):
        return "epistemologia-acoes"
    if path.startswith("memorias/timelines/"):
        return "timelines"
    if path.startswith("memorias/evidencias/"):
        return "evidencias"
    if path.startswith("memorias/cobertura/"):
        return "cobertura"
    if path.startswith("docs/referencias/"):
        return "referencias"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith(".github/"):
        return "github"
    return "outros"


def entity_for(path: str) -> str:
    mapping = {
        "memorias/pessoas/": "person",
        "memorias/holons/": "holon",
        "memorias/papeis/": "role",
        "memorias/responsabilidades/": "responsibility",
        "memorias/atribuicoes/": "assignment",
        "memorias/projetos/": "project",
        "memorias/iniciativas/": "initiative",
        "memorias/fontes/": "source",
        "memorias/claims/": "claim",
        "memorias/decisoes/": "decision",
        "memorias/insights/": "insight",
        "memorias/acoes/": "action",
        "memorias/timelines/": "timeline",
        "memorias/evidencias/": "evidence",
        "memorias/cobertura/": "coverage",
        "memorias/ontologia/": "ontology",
    }
    for prefix, entity in mapping.items():
        if path.startswith(prefix):
            return entity
    if path.startswith("memorias/"):
        return "context-memory"
    if path.startswith("docs/referencias/templates/wiki/"):
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
    print("- Review any `memorias/financeiro` changes for transaction-level detail.")
    print("- Review any `docs/thoughtworks` changes for payroll, email, or third-party data.")
    print("- Confirm `docs/` changes are references/templates/snapshots, not live memory.")
    print()
    print("## Validation checklist")
    print()
    print("- [ ] `python3 scripts/wiki_audit.py --check`")
    print("- [ ] `git diff --check`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
