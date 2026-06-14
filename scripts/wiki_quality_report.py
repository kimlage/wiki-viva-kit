#!/usr/bin/env python3
"""Report Wiki Viva v6.3 quality and cost telemetry.

The report is deterministic and has no LLM client. Cost is measured for control
and comparison only; v6.3 intentionally does not enforce a hard budget.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.quality import build_quality_report, render_markdown

# Versioned ratchet baseline (committed). Holds the agreed ceiling for every
# defect counter; the --ratchet gate fails if the current report regresses past
# any of these numbers. Lives outside data/derived (which is gitignored).
DEFAULT_RATCHET_BASELINE = "data/quality/quality-report-baseline.json"

# Defect counters from report["summary"]: lower is always better. Only metrics
# where an INCREASE is a regression belong here. Volume/telemetry fields
# (pages_total, repeated_blocks, contexts, page_types, token estimates, cache
# rates) are intentionally excluded — they grow with the wiki by design.
RATCHET_DEFECT_COUNTERS = (
    "bad_repetition_blocks",
    "low_information_density_pages",
    "thin_link_pages",
    "orphan_actions",
    "contexts_without_role",
    "responsibilities_without_action",
    "role_responsibility_edge_mismatch",
    "events_without_consolidated_into",
    "events_without_impact_closure",
    "quality_exemption_missing_reason",
)


def ratchet_counters(report: dict) -> dict[str, int]:
    """Extract the defect counters tracked by the ratchet from a report.

    Missing keys default to 0 so a baseline stays comparable even if a counter
    is added or temporarily absent from the report.
    """
    summary = report.get("summary", {})
    return {key: int(summary.get(key, 0)) for key in RATCHET_DEFECT_COUNTERS}


def compare_ratchet(current: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Return human-readable regressions where a counter exceeds the baseline.

    A counter absent from the baseline is treated as 0 (newly tracked defect),
    so it may only stay at 0 to pass. Improvements (current < baseline) pass.
    """
    regressions: list[str] = []
    for key in RATCHET_DEFECT_COUNTERS:
        now = int(current.get(key, 0))
        ceiling = int(baseline.get(key, 0))
        if now > ceiling:
            regressions.append(f"{key}={now} > baseline={ceiling}")
    return regressions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format (default: markdown)",
    )
    parser.add_argument("--output", help="write report to this repo-relative path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when quality metrics exceed their configured thresholds",
    )
    parser.add_argument(
        "--snapshot",
        nargs="?",
        const=DEFAULT_RATCHET_BASELINE,
        default=None,
        metavar="PATH",
        help=(
            "write the current defect counters as a ratchet snapshot to PATH "
            f"(repo-relative; default: {DEFAULT_RATCHET_BASELINE}). Use this to "
            "(re)generate the committed baseline after an intentional change."
        ),
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help=(
            "compare current defect counters against the versioned baseline and "
            "fail (rc=1) if any counter increased (only same-or-better passes)"
        ),
    )
    parser.add_argument(
        "--ratchet-baseline",
        default=DEFAULT_RATCHET_BASELINE,
        metavar="PATH",
        help=(
            "repo-relative path to the versioned ratchet baseline "
            f"(default: {DEFAULT_RATCHET_BASELINE})"
        ),
    )
    parser.add_argument(
        "--max-bad-repetition",
        type=int,
        default=None,
        help=(
            "maximum same-context/same-type repetition blocks allowed under --check "
            "(default: audit.quality_max_bad_repetition or 0)"
        ),
    )
    parser.add_argument(
        "--max-low-density",
        type=int,
        default=None,
        help=(
            "maximum low-information-density pages allowed under --check "
            "(default: audit.quality_max_low_density or 0)"
        ),
    )
    parser.add_argument(
        "--max-responsibilities-without-action",
        type=int,
        default=None,
        help=(
            "maximum responsibilities without a linked action allowed under --check "
            "(default: audit.quality_max_responsibilities_without_action or unlimited)"
        ),
    )
    parser.add_argument(
        "--max-contexts-without-role",
        type=int,
        default=None,
        help=(
            "maximum operational contexts without a role allowed under --check "
            "(default: audit.quality_max_contexts_without_role or unlimited)"
        ),
    )
    parser.add_argument(
        "--max-orphan-actions",
        type=int,
        default=None,
        help=(
            "maximum actions without a responsibility allowed under --check "
            "(default: audit.quality_max_orphan_actions or unlimited)"
        ),
    )
    parser.add_argument(
        "--max-role-responsibility-mismatch",
        type=int,
        default=None,
        help=(
            "maximum role/responsibility reciprocity mismatches allowed under --check "
            "(default: audit.quality_max_role_responsibility_mismatch or unlimited)"
        ),
    )
    args = parser.parse_args(argv)

    config = load_config(ROOT)
    report = build_quality_report(ROOT, config)
    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        output = render_markdown(report)

    if args.output:
        out = ROOT / args.output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT).as_posix()}")
    else:
        print(output, end="" if output.endswith("\n") else "\n")

    if args.snapshot:
        snapshot = ratchet_counters(report)
        snap_path = ROOT / args.snapshot
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote ratchet snapshot {snap_path.relative_to(ROOT).as_posix()}")

    if args.ratchet:
        baseline_path = ROOT / args.ratchet_baseline
        if not baseline_path.exists():
            print(
                "wiki_quality_report: ratchet baseline missing at "
                f"{args.ratchet_baseline}; create it with "
                f"`--snapshot {args.ratchet_baseline}` and commit it.",
                file=sys.stderr,
            )
            return 2
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"wiki_quality_report: cannot read ratchet baseline "
                f"{args.ratchet_baseline}: {exc}",
                file=sys.stderr,
            )
            return 2
        current = ratchet_counters(report)
        regressions = compare_ratchet(current, baseline)
        if regressions:
            print(
                "wiki_quality_report: quality ratchet regressed "
                f"({len(regressions)} counter(s) increased):",
                file=sys.stderr,
            )
            for line in regressions:
                print(f"  - {line}", file=sys.stderr)
            print(
                "Fix the regression, or — if the increase is intentional and "
                f"justified — refresh the baseline with `--snapshot "
                f"{args.ratchet_baseline}` and commit it.",
                file=sys.stderr,
            )
            return 1

    if args.check:
        bad = int(report["summary"]["bad_repetition_blocks"])
        low_density = int(report["summary"]["low_information_density_pages"])
        missing_exemption_reason = int(
            report["summary"].get("quality_exemption_missing_reason", 0)
        )
        try:
            max_bad_repetition = int(
                args.max_bad_repetition
                if args.max_bad_repetition is not None
                else config.audit.get("quality_max_bad_repetition", 0)
            )
            max_low_density = int(
                args.max_low_density
                if args.max_low_density is not None
                else config.audit.get("quality_max_low_density", 0)
            )
        except (TypeError, ValueError):
            print(
                "wiki_quality_report: invalid quality threshold in args/config",
                file=sys.stderr,
            )
            return 2
        if bad > max_bad_repetition:
            print(
                f"wiki_quality_report: bad_repetition_blocks={bad} "
                f"> max_bad_repetition={max_bad_repetition}",
                file=sys.stderr,
            )
            return 1
        if low_density > max_low_density:
            print(
                f"wiki_quality_report: low_information_density_pages={low_density} "
                f"> max_low_density={max_low_density}",
                file=sys.stderr,
            )
            return 1
        if missing_exemption_reason:
            print(
                "wiki_quality_report: "
                f"quality_exemption_missing_reason={missing_exemption_reason}",
                file=sys.stderr,
            )
            return 1

        # Operational model coverage (Fase 5). Telemetry-first: the default
        # threshold is unlimited (None) so the gate only bites once a repo opts
        # in via args or audit.quality_max_* config. Loose by design.
        coverage_gates = (
            (
                "responsibilities_without_action",
                args.max_responsibilities_without_action,
                "quality_max_responsibilities_without_action",
            ),
            (
                "contexts_without_role",
                args.max_contexts_without_role,
                "quality_max_contexts_without_role",
            ),
            (
                "orphan_actions",
                args.max_orphan_actions,
                "quality_max_orphan_actions",
            ),
            (
                "role_responsibility_edge_mismatch",
                args.max_role_responsibility_mismatch,
                "quality_max_role_responsibility_mismatch",
            ),
        )
        for metric, arg_value, config_key in coverage_gates:
            raw_max = arg_value if arg_value is not None else config.audit.get(config_key)
            if raw_max is None:
                continue
            try:
                threshold = int(raw_max)
            except (TypeError, ValueError):
                print(
                    f"wiki_quality_report: invalid threshold for {metric} in args/config",
                    file=sys.stderr,
                )
                return 2
            count = int(report["summary"][metric])
            if count > threshold:
                print(
                    f"wiki_quality_report: {metric}={count} > max={threshold}",
                    file=sys.stderr,
                )
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
