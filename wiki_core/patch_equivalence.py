"""Prove that a rebased proposal carries the same patch (issue #522).

Compares the cumulative patch of the reviewed head against the rebased head
with `git patch-id --stable`, and reports whether `git range-diff` sees every
commit as unchanged. Local Git objects only: no fetch, no provider call, no
writes. The printed `Equivalence:` line is the proof for the integration
handoff; a different or empty patch needs the normal review.

Run from the repository root: `python3 -m wiki_core.patch_equivalence
--reviewed <sha> --rebased <sha> [--onto <ref>]`.
Exit status: 0 identical, 1 different or not provable, 2 invalid input.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from wiki_core.git_env import local_git_environment, local_git_executable


class EquivalenceError(ValueError):
    """The comparison cannot be established from local Git objects."""


def _git(root, args: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        result = subprocess.run([local_git_executable(), "--no-lazy-fetch", *args], cwd=root,
                                env=local_git_environment(), input=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        raise EquivalenceError("Git is unavailable") from exc
    if result.returncode:
        raise EquivalenceError("Git could not read the requested commits")
    return result.stdout


def commit(root, ref: str) -> str:
    if not ref or ref.startswith("-") or any(ord(c) < 32 for c in ref):
        raise EquivalenceError("invalid revision")
    sha = os.fsdecode(_git(root, ["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"])).strip()
    if len(sha) not in (40, 64) or any(c not in "0123456789abcdef" for c in sha):
        raise EquivalenceError("invalid revision")
    return sha


def patch_id(root, base: str, head: str) -> str | None:
    diff = _git(root, ["diff", "--no-ext-diff", "--no-textconv", "--binary", "--full-index", base, head])
    if not diff:
        return None
    out = os.fsdecode(_git(root, ["patch-id", "--stable"], stdin=diff)).split()
    return out[0] if out else None


def range_diff_unchanged(root, old_base: str, old_head: str, new_base: str, new_head: str) -> bool:
    out = os.fsdecode(_git(root, ["range-diff", "--no-color",
                                  f"{old_base}..{old_head}", f"{new_base}..{new_head}"])).splitlines()
    pairs = [line for line in out if line and line[0].isdigit() or line.startswith("-:")]
    return bool(pairs) and all(" = " in line for line in pairs)


def compare(root, old_head: str, new_head: str, old_base: str | None = None,
            new_base: str = "refs/remotes/origin/main") -> dict:
    new_base_sha = commit(root, new_base)
    old_head_sha, new_head_sha = commit(root, old_head), commit(root, new_head)
    if old_base is None:
        bases = os.fsdecode(_git(root, ["merge-base", "--all", old_head_sha, new_base_sha])).split()
        if len(bases) != 1:
            raise EquivalenceError("a unique old base is unavailable; pass --old-base")
        old_base_sha = bases[0]
    else:
        old_base_sha = commit(root, old_base)
    try:
        _git(root, ["merge-base", "--is-ancestor", new_base_sha, new_head_sha])
    except EquivalenceError:
        raise EquivalenceError("the rebased head does not contain the new base") from None
    old_id = patch_id(root, old_base_sha, old_head_sha)
    new_id = patch_id(root, new_base_sha, new_head_sha)
    if old_id is None or new_id is None:
        verdict = "empty_patch"
    else:
        verdict = "identical" if old_id == new_id else "different"
    return {"verdict": verdict, "patch_id": new_id if verdict == "identical" else None,
            "old_base": old_base_sha, "old_head": old_head_sha,
            "new_base": new_base_sha, "new_head": new_head_sha,
            "range_diff_unchanged": verdict != "empty_patch" and range_diff_unchanged(
                root, old_base_sha, old_head_sha, new_base_sha, new_head_sha)}


def proof_line(result: dict) -> str:
    return (f"Equivalence: {result['verdict']} patch-id={result['patch_id'] or 'none'} "
            f"reviewed={result['old_head']} base={result['old_base']} "
            f"rebased={result['new_head']} onto={result['new_base']} "
            f"range-diff={'unchanged' if result['range_diff_unchanged'] else 'changed'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m wiki_core.patch_equivalence", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    parser.add_argument("--reviewed", required=True, help="head SHA that received the independent review")
    parser.add_argument("--rebased", required=True, help="new head SHA after the rebase")
    parser.add_argument("--reviewed-base", help="base of the reviewed head (default: its merge-base with --onto)")
    parser.add_argument("--onto", default="refs/remotes/origin/main", help="new base (default: local origin/main)")
    args = parser.parse_args(argv)
    try:
        result = compare(args.root, args.reviewed, args.rebased, args.reviewed_base, args.onto)
    except EquivalenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(proof_line(result))
    return 0 if result["verdict"] == "identical" else 1


if __name__ == "__main__":
    raise SystemExit(main())
