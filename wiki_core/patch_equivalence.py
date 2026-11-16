"""Prove that a clean rebase kept every reviewed commit (issues #522, #523).

Merge-condition case 2: a rebase of an already covered head, with no conflict
and no new commit, counts as covered only when `git range-diff` shows every
commit as `=`, or when the `git patch-id --stable` of each commit equals that
of the covered head (`git log -p --reverse <base>..<head> | git patch-id
--stable` on both sides). Commits must also keep their positions. A squash, a
new, dropped or reordered commit, or any changed content is `different`; a
merge commit in either range is `not_provable`. Local Git objects only: no
fetch, no provider call, no writes. The printed `Equivalence:` line and the
per-commit lines are the proof to record on the proposal.

Run from the repository root: `python3 -m wiki_core.patch_equivalence
--reviewed <sha> --rebased <sha> [--onto <ref>]`.
Exit status: 0 identical, 1 different or not provable, 2 invalid input.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from wiki_core.git_env import local_git_environment, local_git_executable

_SHA = r"[0-9a-f]{40}(?:[0-9a-f]{24})?"
_RANGE_PAIR = re.compile(r"^\s*(\d+|-):\s+(\S+)\s+([=!<>])\s+(\d+|-):\s+(\S+)")


class EquivalenceError(ValueError):
    """The comparison cannot be established from local Git objects."""


def _git(root, args: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        result = subprocess.run([local_git_executable(), "--no-lazy-fetch", "-c", "log.showSignature=false",
                                 "-c", "color.ui=false", *args], cwd=root,
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
    if not re.fullmatch(_SHA, sha):
        raise EquivalenceError("invalid revision")
    return sha


def commit_patch_ids(root, base: str, head: str) -> tuple[list[tuple[str, str | None]], bool]:
    """Commits of `base..head` in order with their stable patch-ids; merges flagged."""
    span = f"{base}..{head}"
    commits = os.fsdecode(_git(root, ["rev-list", "--reverse", span])).split()
    merges = bool(os.fsdecode(_git(root, ["rev-list", "--merges", span])).split())
    log = _git(root, ["log", "-p", "--reverse", "--no-merges", "--no-ext-diff", "--no-textconv",
                      "--full-index", "--binary", "--pretty=format:commit %H", span])
    ids: dict[str, str] = {}
    for line in os.fsdecode(_git(root, ["patch-id", "--stable"], stdin=log)).splitlines():
        parts = line.split()
        if len(parts) == 2:
            ids[parts[1]] = parts[0]
    return [(sha, ids.get(sha)) for sha in commits], merges


def range_diff_unchanged(root, old_base: str, old_head: str, new_base: str, new_head: str) -> bool:
    """Every pair `=` at the same position, and nothing added or dropped."""
    out = os.fsdecode(_git(root, ["range-diff", "--no-color",
                                  f"{old_base}..{old_head}", f"{new_base}..{new_head}"])).splitlines()
    pairs = [match for match in map(_RANGE_PAIR.match, out) if match]
    return bool(pairs) and all(m.group(3) == "=" and m.group(1) == m.group(4) != "-" for m in pairs)


def compare(root, old_head: str, new_head: str, old_base: str | None = None,
            new_base: str = "refs/remotes/origin/main") -> dict:
    new_base_sha = commit(root, new_base)
    old_head_sha, new_head_sha = commit(root, old_head), commit(root, new_head)
    if old_base is None:
        bases = os.fsdecode(_git(root, ["merge-base", "--all", old_head_sha, new_base_sha])).split()
        if len(bases) != 1:
            raise EquivalenceError("a unique old base is unavailable; pass --reviewed-base")
        old_base_sha = bases[0]
    else:
        old_base_sha = commit(root, old_base)
    try:
        _git(root, ["merge-base", "--is-ancestor", new_base_sha, new_head_sha])
    except EquivalenceError:
        raise EquivalenceError("the rebased head does not contain the new base") from None
    old, old_merges = commit_patch_ids(root, old_base_sha, old_head_sha)
    new, new_merges = commit_patch_ids(root, new_base_sha, new_head_sha)
    pairs = [(o[0], o[1], n[0], n[1]) for o, n in zip(old, new)]
    per_commit = (len(old) == len(new) and bool(old)
                  and all(o_id is not None and o_id == n_id for _, o_id, _, n_id in pairs))
    range_diff = (bool(old) and bool(new) and not (old_merges or new_merges)
                  and range_diff_unchanged(root, old_base_sha, old_head_sha, new_base_sha, new_head_sha))
    if old_merges or new_merges:
        verdict = "not_provable"
    elif not old or not new:
        verdict = "empty_patch"
    elif len(old) != len(new):
        verdict = "different"
    else:
        verdict = "identical" if (per_commit or range_diff) else "different"
    return {"verdict": verdict, "commits": (len(old), len(new)), "pairs": pairs,
            "per_commit_patch_id": per_commit, "range_diff_unchanged": range_diff,
            "old_base": old_base_sha, "old_head": old_head_sha,
            "new_base": new_base_sha, "new_head": new_head_sha}


def proof_line(result: dict) -> str:
    old_count, new_count = result["commits"]
    commits = str(old_count) if old_count == new_count else f"{old_count}->{new_count}"
    return (f"Equivalence: {result['verdict']} commits={commits} "
            f"patch-id={'per-commit-match' if result['per_commit_patch_id'] else 'differs'} "
            f"range-diff={'all-equal' if result['range_diff_unchanged'] else 'changed'} "
            f"reviewed={result['old_head']} base={result['old_base']} "
            f"rebased={result['new_head']} onto={result['new_base']}")


def proof_details(result: dict) -> list[str]:
    lines = []
    for index, (old_sha, old_id, new_sha, new_id) in enumerate(result["pairs"], 1):
        mark = "=" if old_id is not None and old_id == new_id else "!"
        lines.append(f"  {index}: {old_sha[:12]} {(old_id or 'empty')[:12]} {mark} "
                     f"{new_sha[:12]} {(new_id or 'empty')[:12]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m wiki_core.patch_equivalence", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    parser.add_argument("--reviewed", required=True, help="head SHA covered by the independent review")
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
    for line in proof_details(result):
        print(line)
    return 0 if result["verdict"] == "identical" else 1


if __name__ == "__main__":
    raise SystemExit(main())
