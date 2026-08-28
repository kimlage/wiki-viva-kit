#!/usr/bin/env python3
"""Compile the one-time pre-gate action lifecycle adoption receipt."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.action_adoption import (  # noqa: E402
    ACTION_ADOPTION_RECEIPT_PATH,
    action_documents_at_commit,
    compile_action_adoption_receipt,
    render_action_adoption_receipt,
    verify_action_adoption_git_contract,
)
from wiki_core.config import load_config  # noqa: E402


def _resolve_commit(ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode or len(value) != 40:
        raise ValueError(f"unresolvable commit ref: {ref}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-base", default="origin/main")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--gate-introduced", required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write the root consumer receipt {ACTION_ADOPTION_RECEIPT_PATH}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(ROOT)
    audit_base = _resolve_commit(args.audit_base)
    baseline = _resolve_commit(args.baseline)
    gate = _resolve_commit(args.gate_introduced)
    memory_root = str(config.paths["memory_root"])
    documents = action_documents_at_commit(ROOT, baseline, memory_root)
    receipt = compile_action_adoption_receipt(
        repo_id=config.repo_id,
        audit_base_commit=audit_base,
        baseline_commit=baseline,
        gate_introduced_commit=gate,
        recorded_at=args.recorded_at,
        reason=args.reason,
        documents=documents,
    )
    errors = verify_action_adoption_git_contract(
        ROOT,
        receipt,
        repo_id=config.repo_id,
        memory_root=memory_root,
        audit_base_commit=audit_base,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    rendered = render_action_adoption_receipt(receipt)
    target = ROOT / ACTION_ADOPTION_RECEIPT_PATH
    if args.write:
        if target.exists():
            print(
                f"ERROR: {ACTION_ADOPTION_RECEIPT_PATH} already exists; "
                "the adoption receipt is singular and immutable",
                file=sys.stderr,
            )
            return 1
        target.write_text(rendered, encoding="utf-8")
        print(
            f"{ACTION_ADOPTION_RECEIPT_PATH}: adopted {receipt['action_count']} "
            f"pre-gate action(s) ({receipt['action_inventory_sha256'][:12]})"
        )
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
