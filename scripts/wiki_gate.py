#!/usr/bin/env python3
"""Living gate: lists proposals, applies transitions and rebases/supersedes.

Default proposals directory: memorias/sistema/ingestao (proposals live flat).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.gate import read_proposal, rebase_pending, write_state

DEFAULT_DIR = ROOT / "memorias" / "sistema" / "ingestao"


def _iter_proposals(directory: Path):
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == "README.md":
            continue
        yield read_proposal(md_path)


def cmd_list(directory: Path) -> int:
    if not directory.is_dir():
        print(f"directory does not exist: {directory}", file=sys.stderr)
        return 1
    rows = list(_iter_proposals(directory))
    if not rows:
        print(f"no proposals in {directory}")
        return 0
    header = f"{'gate_state':<18} {'page_id':<40} {'context':<12} {'created_at':<12} file"
    print(header)
    print("-" * len(header))
    for proposal in rows:
        print(
            f"{proposal.gate_state:<18} "
            f"{(proposal.page_id or '-'):<40} "
            f"{(proposal.context or '-'):<12} "
            f"{(proposal.created_at or '-'):<12} "
            f"{proposal.path.name}"
        )
    return 0


def cmd_transition(path: Path, to_state: str, reason: str | None) -> int:
    if not path.is_file():
        print(f"file does not exist: {path}", file=sys.stderr)
        return 1
    try:
        proposal = write_state(path, to_state, reason=reason)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {proposal.path.name} -> {proposal.gate_state}")
    return 0


def cmd_rebase(directory: Path, page_id: str | None, context: str | None, rebase_key: str | None) -> int:
    if not directory.is_dir():
        print(f"directory does not exist: {directory}", file=sys.stderr)
        return 1
    result = rebase_pending(directory, page_id=page_id, context=context, rebase_key=rebase_key)
    kept = result["kept"]
    superseded = result["superseded"]

    def _name(value: object) -> str:
        return Path(value).name if isinstance(value, Path) else str(value)

    if isinstance(kept, list):
        if kept:
            print("kept:")
            for item in kept:
                print(f"  {_name(item)}")
        else:
            print("kept: (none)")
    else:
        print(f"kept: {_name(kept) if kept else '(none)'}")

    if superseded:
        print("superseded:")
        for item in superseded:
            print(f"  {_name(item)}")
    else:
        print("superseded: (none)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="proposals directory")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list proposals and states")
    group.add_argument("--transition", metavar="PATH", type=Path, help="proposal file to transition")
    group.add_argument("--rebase", action="store_true", help="apply rebase_pending")

    parser.add_argument("--to", metavar="STATE", help="target state (with --transition)")
    parser.add_argument("--reason", help="reason recorded in gate_history")
    parser.add_argument("--page", metavar="PAGE_ID", help="filter rebase by page_id")
    parser.add_argument("--context", metavar="CTX", help="filter rebase by context")
    parser.add_argument("--rebase-key", metavar="KEY", help="filter rebase by logical target (rebase_key)")
    args = parser.parse_args()

    if args.list:
        return cmd_list(args.dir)
    if args.transition is not None:
        if not args.to:
            parser.error("--transition requires --to <state>")
        return cmd_transition(args.transition, args.to, args.reason)
    if args.rebase:
        return cmd_rebase(args.dir, args.page, args.context, args.rebase_key)
    parser.error("no action provided")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
