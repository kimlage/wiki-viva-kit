#!/usr/bin/env python3
"""Inspect documentary occurrences using the configured exact v1 snapshot pair.

No freshness evaluation, role inference, source edits or configuration overrides.
Output contains private source text; retain it inside the consumer boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    from _common import ROOT

from scripts.wiki_page_graph import (
    collect_git_changes, project_memory_at_commit, run_git,
)
from wiki_core.config import load_config
from wiki_core.document_record_review import review_records
from wiki_core.document_records import artifact_paths
from wiki_core.freshness_impact import authored_graph
from wiki_core.semantic_inventory import _authored_pages


def repository_review(root: Path, targets):
    """Read the configured pair once and refuse changing inputs."""
    config_path = root / "wiki.config.yaml"
    config_bytes = config_path.read_bytes()
    config = load_config(root)
    base_ref = config.audit.get("freshness_base")
    rel = config.audit.get("freshness_records")
    if not isinstance(base_ref, str) or not isinstance(rel, str) or not base_ref or not rel:
        raise ValueError("configured freshness_base and freshness_records are required")
    if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
        raise ValueError("record contract must be repository-relative")
    record_path = root / rel
    if record_path.is_symlink() or not record_path.resolve().is_relative_to(root.resolve()):
        raise ValueError("record contract must be a local repository file")
    raw_contract = record_path.read_bytes()
    contract = json.loads(raw_contract)
    head = run_git(["rev-parse", "--verify", "HEAD^{commit}"], root=root).strip()
    base_sha = run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], root=root).strip()
    run_git(["merge-base", "--is-ancestor", base_sha, head], root=root)
    changes = collect_git_changes(base_sha, root=root)
    current = authored_graph(root, config)
    base = project_memory_at_commit(base_sha, authored_graph, root=root)
    if current["errors"] or base["errors"]:
        raise ValueError("authored graph diagnostics must be resolved before review")
    paths = artifact_paths(root, contract)
    artifacts = {key: path.read_bytes() for key, path in paths.items()}
    memory_changes = set(changes.paths) & (set(current["documents"]) | set(base["documents"]))
    report = review_records(current, base, memory_changes, contract,
                            targets=targets, artifact_inputs=artifacts)
    for path, text in current["documents"].items():
        if (root / path).is_symlink() or (root / path).read_bytes() != text.encode("utf-8"):
            raise ValueError("review inputs changed during inspection")
    if (config_path.read_bytes() != config_bytes or record_path.read_bytes() != raw_contract
            or any(path.read_bytes() != artifacts[key] for key, path in paths.items())
            or {p.path for p in _authored_pages(root, config)} != set(current["documents"])
            or run_git(["rev-parse", "HEAD^{commit}"], root=root).strip() != head
            or run_git(["rev-parse", f"{base_ref}^{{commit}}"], root=root).strip() != base_sha
            or collect_git_changes(base_sha, root=root) != changes):
        raise ValueError("review inputs changed during inspection")
    report.update(base_sha=base_sha, head_sha=head,
        config_sha256=hashlib.sha256(config_bytes).hexdigest(),
        contract_file_sha256=hashlib.sha256(raw_contract).hexdigest(),
        artifact_sha256={f"{o}:{aid}": hashlib.sha256(data).hexdigest()
                         for (o, aid), data in artifacts.items()})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", required=True,
                        help="Exact authored repository path; repeat for the full proposal")
    parser.add_argument("--out", type=Path, help="NEW private JSON output; otherwise stdout")
    args = parser.parse_args(argv)
    try:
        report = repository_review(ROOT, args.target)
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                handle.write(text)
        else:
            print(text, end="")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"documentary review unavailable: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
