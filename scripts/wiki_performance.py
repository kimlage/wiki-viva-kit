#!/usr/bin/env python3
"""Plan, run, resume, verify and report Wiki Viva performance evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.performance.models import PerformanceContractError
from wiki_core.performance.runner import PerformanceRunner


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--profile", choices=("cycle1", "standard", "stress", "soak"), required=True)
    plan.add_argument("--seed", type=int, default=469)
    plan.add_argument("--repetitions", type=int, default=2)
    plan.add_argument("--out", type=Path, required=True)

    dry = sub.add_parser("dry-run")
    dry.add_argument("--plan", type=Path, required=True)

    for name in ("run", "resume"):
        action = sub.add_parser(name)
        action.add_argument("--plan", type=Path, required=True)
        action.add_argument("--evidence-root", type=Path, required=True)
        action.add_argument("--allow-heavy", action="store_true")
        action.add_argument("--confirm-plan-sha")

    verify = sub.add_parser("verify")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--receipt", type=Path)

    report = sub.add_parser("report")
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--receipt", type=Path, required=True)
    report.add_argument("--out", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    runner = PerformanceRunner(ROOT)
    try:
        if args.command == "plan":
            value = runner.create_plan(
                args.out,
                profile_name=args.profile,
                seed=args.seed,
                repetitions=args.repetitions,
            )
        elif args.command == "dry-run":
            value = runner.dry_run(args.plan)
        elif args.command in {"run", "resume"}:
            value = runner.run(
                args.plan,
                args.evidence_root,
                resume=args.command == "resume",
                allow_heavy=args.allow_heavy,
                confirm_plan_sha=args.confirm_plan_sha,
            )
        elif args.command == "verify":
            value = runner.verify(args.plan, args.receipt)
        else:
            value = runner.report(args.plan, args.receipt, args.out)
    except PerformanceContractError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    _print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
