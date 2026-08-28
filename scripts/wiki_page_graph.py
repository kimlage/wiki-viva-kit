#!/usr/bin/env python3
"""Build and validate the Wiki Viva page graph."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config  # noqa: E402
from wiki_core.graph import (  # noqa: E402
    PageGraph,
    build_page_graph,
    compute_impact,
    graph_to_dict,
    min_outbound_violations,
    orphan_pages,
    unreachable_pages,
)
from wiki_core.paths import WikiPaths  # noqa: E402


class GitCommandError(RuntimeError):
    """A Git read failed; impact evidence must stop instead of shrinking."""

    def __init__(
        self,
        args: list[str],
        *,
        returncode: int | None,
        detail: str,
    ) -> None:
        self.git_args = tuple(args)
        self.returncode = returncode
        self.detail = " ".join(detail.split())[:500]
        command = "git " + " ".join(args)
        suffix = f" (exit {returncode})" if returncode is not None else ""
        if self.detail:
            suffix += f": {self.detail}"
        super().__init__(f"{command}{suffix}")


@dataclass(frozen=True)
class GitChanges:
    paths: frozenset[str]
    deleted_paths: frozenset[str]
    untracked_paths: frozenset[str]


def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitCommandError(
            args,
            returncode=None,
            detail=str(exc),
        ) from exc
    if result.returncode != 0:
        raise GitCommandError(
            args,
            returncode=result.returncode,
            detail=result.stderr,
        )
    return result.stdout


def resolve_base(base: str) -> str | None:
    """Resolve an explicit impact base to its full commit SHA."""
    try:
        resolved = run_git(
            ["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"]
        ).strip()
    except GitCommandError as exc:
        if exc.returncode == 1:
            return None
        raise
    return resolved or None


def base_is_ancestor(base_sha: str) -> bool:
    """Return whether the exact review base is an ancestor of HEAD."""

    try:
        run_git(["merge-base", "--is-ancestor", base_sha, "HEAD"])
    except GitCommandError as exc:
        if exc.returncode == 1:
            return False
        raise
    return True


def _git_paths(args: list[str]) -> set[str]:
    """Read a NUL-delimited Git path list without corrupting unusual names."""

    return {path for path in run_git(args).split("\0") if path}


def collect_git_changes(base_sha: str) -> GitChanges:
    """Collect committed, staged, unstaged, untracked and deleted paths."""

    committed_args = ["diff", "--name-only", "-z", f"{base_sha}..HEAD", "--"]
    unstaged_args = ["diff", "--name-only", "-z", "--"]
    staged_args = ["diff", "--cached", "--name-only", "-z", "--"]
    untracked_args = ["ls-files", "--others", "--exclude-standard", "-z", "--"]
    deleted_commands = (
        [
            "diff",
            "--name-only",
            "--diff-filter=D",
            "-z",
            f"{base_sha}..HEAD",
            "--",
        ],
        ["diff", "--name-only", "--diff-filter=D", "-z", "--"],
        ["diff", "--cached", "--name-only", "--diff-filter=D", "-z", "--"],
    )
    untracked = _git_paths(untracked_args)
    paths = (
        _git_paths(committed_args)
        | _git_paths(unstaged_args)
        | _git_paths(staged_args)
        | untracked
    )
    deleted = set().union(*(_git_paths(command) for command in deleted_commands))
    return GitChanges(
        paths=frozenset(paths),
        deleted_paths=frozenset(deleted),
        untracked_paths=frozenset(untracked),
    )


def changed_paths(base_sha: str) -> set[str]:
    """Compatibility wrapper returning the complete current path set."""

    return set(collect_git_changes(base_sha).paths)


def _safe_materialized_path(root: Path, rel: str) -> Path:
    pure = PurePosixPath(rel)
    if (
        not rel
        or pure.is_absolute()
        or "\\" in rel
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"unsafe repository path at impact base: {rel!r}")
    return root.joinpath(*pure.parts)


def build_page_graph_at_commit(base_sha: str) -> PageGraph:
    """Materialize the configured Markdown memory at one immutable commit."""

    config_text = run_git(["show", f"{base_sha}:wiki.config.yaml"])
    with tempfile.TemporaryDirectory(prefix="wiki-page-graph-base-") as temp_dir:
        base_root = Path(temp_dir)
        (base_root / "wiki.config.yaml").write_text(
            config_text,
            encoding="utf-8",
            errors="surrogateescape",
        )
        base_config = load_config(base_root)
        memory_root = str(base_config.paths["memory_root"]).rstrip("/")
        _safe_materialized_path(base_root, memory_root)
        tree_paths = _git_paths(
            [
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                base_sha,
                "--",
                memory_root,
            ]
        )
        for rel in sorted(path for path in tree_paths if path.lower().endswith(".md")):
            target = _safe_materialized_path(base_root, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                run_git(["show", f"{base_sha}:{rel}"]),
                encoding="utf-8",
                errors="surrogateescape",
            )
        return build_page_graph(base_root, base_config)


def graph_path(config: WikiConfig) -> Path:
    return WikiPaths(ROOT, config).derived_root / "page-graph" / "page-graph.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write data/derived/wiki/page-graph/page-graph.json",
    )
    parser.add_argument(
        "--check", action="store_true", help="return non-zero for graph errors"
    )
    parser.add_argument(
        "--impact",
        action="store_true",
        help="print impacted memory pages for the current diff",
    )
    parser.add_argument(
        "--base", help="explicit commit or ref for --impact (required with --impact)"
    )
    args = parser.parse_args()

    base_sha: str | None = None
    head_sha: str | None = None
    base_graph: PageGraph | None = None
    changes: GitChanges | None = None
    if args.impact:
        if not args.base:
            parser.error(
                "--impact requires --base <ref-or-sha> (base=null, base_sha=null)"
            )
        try:
            base_sha = resolve_base(args.base)
        except GitCommandError as exc:
            parser.error(f"could not resolve impact base safely: {exc}")
        if not base_sha:
            parser.error(
                f"--impact base={args.base!r} could not be resolved to a commit (base_sha=null)"
            )
        try:
            is_ancestor = base_is_ancestor(base_sha)
        except GitCommandError as exc:
            parser.error(f"could not validate impact-base ancestry: {exc}")
        if not is_ancestor:
            parser.error(
                f"--impact base={args.base!r} base_sha={base_sha} is not an "
                "ancestor of HEAD; refusing hidden merge-base semantics"
            )
        try:
            changes = collect_git_changes(base_sha)
            base_graph = build_page_graph_at_commit(base_sha)
            head_sha = resolve_base("HEAD")
            if not head_sha:
                raise ValueError("HEAD could not be resolved to a commit")
        except (GitCommandError, OSError, ValueError) as exc:
            parser.error(f"could not collect exact-base impact evidence: {exc}")

    config = load_config(ROOT)
    graph = build_page_graph(ROOT, config)

    if args.write:
        out = graph_path(config)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(graph_to_dict(graph), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"wrote {out.relative_to(ROOT).as_posix()}",
            file=sys.stderr if args.impact else sys.stdout,
        )

    errors: list[str] = []
    warnings: list[str] = []
    audit_config = config.audit
    root_page = str(
        audit_config.get("reachability_root")
        or config.paths["memory_root"].rstrip("/") + "/index.md"
    )
    for rel in orphan_pages(graph, set(audit_config.get("orphan_exempt_types") or [])):
        errors.append(f"{rel}: orphan memory page")
    for rel in unreachable_pages(graph, root_page):
        errors.append(f"{rel}: unreachable from {root_page}")
    try:
        minimum = int(str(audit_config.get("min_outbound_links", 0) or 0))
    except ValueError:
        minimum = 0
        errors.append("config: audit.min_outbound_links invalid (integer expected)")
    if minimum > 0:
        for rel in min_outbound_violations(graph, minimum=minimum):
            warnings.append(f"{rel}: fewer than {minimum} outbound graph links")

    if args.impact:
        assert (
            args.base is not None
            and base_sha is not None
            and head_sha is not None
            and base_graph is not None
            and changes is not None
        )
        memory_prefix = base_graph.memory_root.rstrip("/") + "/"
        unrepresented_deletions = sorted(
            path
            for path in changes.deleted_paths
            if path.startswith(memory_prefix)
            and path.lower().endswith(".md")
            and path not in base_graph.nodes
        )
        if unrepresented_deletions:
            parser.error(
                "deleted memory paths were not represented in the exact base graph: "
                + ", ".join(unrepresented_deletions)
            )
        result = compute_impact(
            graph,
            set(changes.paths),
            exempt_types=set(audit_config.get("impact_exempt_types") or []),
            base_graph=base_graph,
        )
        print(
            json.dumps(
                {
                    "schema_version": "wiki_page_graph_impact.v1",
                    "base": args.base,
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "changed_pages": list(result.changed_pages),
                    "removed_pages": list(result.removed_pages),
                    "affected_pages": list(result.affected_pages),
                    "references": {k: list(v) for k, v in result.references.items()},
                    "git_changes": {
                        "path_count": len(changes.paths),
                        "deleted_paths": sorted(changes.deleted_paths),
                        "untracked_paths": sorted(changes.untracked_paths),
                    },
                    "diagnostics": {
                        "errors": errors,
                        "warnings": warnings,
                    },
                    "summary": {
                        "error_count": len(errors),
                        "warning_count": len(warnings),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for warning in warnings:
            print(f"WARN: {warning}")
        for error in errors:
            print(f"ERROR: {error}")
        print(f"wiki_page_graph: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if args.check and errors else 0


if __name__ == "__main__":
    sys.exit(main())
