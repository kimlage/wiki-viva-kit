#!/usr/bin/env python3
"""Operational karma and context vitality (gamification layer of the living wiki).

This script records and aggregates scoring events, without a toxic global ranking.
Acts as a "Score Keeper": APPEND-ONLY to score-events.jsonl under the configured
derived root (default data/derived/wiki/), never editing history.

Examples:
  python3 scripts/wiki_score.py --add --event ingestar_fonte_valida \\
      --actor owner --context system
  python3 scripts/wiki_score.py --add --event criar_insight_aceito \\
      --actor owner --context finance --quality 1.0 --impact 3 --rare
  python3 scripts/wiki_score.py --summary
  python3 scripts/wiki_score.py --dashboard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core import load_config
from wiki_core.paths import WikiPaths
from wiki_core.score import (
    DIMENSIONS,
    EVENT_TYPES,
    badge_display,
    compute_karma,
    context_vitality,
    earned_badges,
    level_display,
    level_for,
    load_events,
    mirror_events,
    record_event,
)

# Ledger location follows the configured derived root (localized repos pin it).
CONFIG = load_config(ROOT)
EVENTS_PATH = WikiPaths(ROOT, CONFIG).derived_root / "score-events.jsonl"


def _add(args: argparse.Namespace, events_path: Path) -> int:
    if args.event not in EVENT_TYPES:
        valid = ", ".join(sorted(EVENT_TYPES))
        print(f"ERROR: unknown event {args.event!r}. Valid: {valid}", file=sys.stderr)
        return 2
    event = record_event(
        events_path,
        event_type=args.event,
        actor=args.actor,
        context=args.context,
        quality=args.quality,
        collaborators=args.collaborators,
        rare=args.rare,
        impact=args.impact,
        ts=args.ts,
    )
    print(
        f"recorded {event.event_type} "
        f"(dimensao={event.dimensao}, base={event.base_points}, "
        f"mult={event.multiplier:g}, final={event.final_points:g}) "
        f"-> {events_path.relative_to(ROOT)}"
    )
    return 0


def _summary(events_path: Path, language: str = "en") -> int:
    events = load_events(events_path)
    if not events:
        print(f"no events in {events_path.relative_to(ROOT)} (record with --add)")
        return 0

    karma = compute_karma(events)
    badges = earned_badges(events)
    level_id = level_for(float(karma["total"]))

    print("== Personal operational karma (private, by dimension; soft decay) ==")
    for dim in DIMENSIONS:
        value = float(karma["by_dimension"].get(dim, 0.0))
        print(f"  {dim:<14} {value:8.2f}")
    print(f"  {'TOTAL':<14} {float(karma['total']):8.2f}")
    print(f"  journey level: {level_display(level_id, language)}")

    print("\n== Vitality by context (collective health, no leaderboard) ==")
    for ctx in sorted(karma["by_context"]):
        vit = context_vitality(events, ctx)
        print(
            f"  {ctx:<14} index={vit['indice_vitalidade']:5.1f}/100 "
            f"score={vit['score_aggregado']:6.2f} "
            f"events={vit['eventos']} participants={vit['participacao_distribuida']}"
        )

    print("\n== Badges earned ==")
    if badges:
        for badge_id in badges:
            display = badge_display(badge_id, language)
            print(f"  - {display['name']} ({display['criterion']})")
    else:
        print("  (none yet)")
    return 0


def _dashboard(events_path: Path, language: str = "en") -> int:
    events = load_events(events_path)
    print("## Vitality by context\n")
    if not events:
        print("_No events recorded yet._")
        return 0
    karma = compute_karma(events)
    print("| Context | Index (0-100) | Aggregate score | Events | Participants |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for ctx in sorted(karma["by_context"]):
        vit = context_vitality(events, ctx)
        print(
            f"| {ctx} | {vit['indice_vitalidade']:.1f} | "
            f"{vit['score_aggregado']:.2f} | {vit['eventos']} | "
            f"{vit['participacao_distribuida']} |"
        )
    badges = earned_badges(events)
    print("\n### Active badges\n")
    if badges:
        for badge_id in badges:
            print(f"- {badge_display(badge_id, language)['name']}")
    else:
        print("_No active badges._")
    print(
        "\n> Collective health indicator, with no toxic global person-vs-person ranking."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--add", action="store_true", help="record an event (append-only)")
    parser.add_argument("--summary", action="store_true", help="karma by dimension, vitality, badges, level")
    parser.add_argument("--dashboard", action="store_true", help="markdown of the vitality section")
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="write a VERSIONED mirror of the ledger (so karma does not reset on a clean clone)",
    )

    parser.add_argument("--event", help="event_type (see EVENT_TYPES)")
    parser.add_argument("--actor", help="id of who performed the event")
    parser.add_argument("--context", help="context/circle/project")
    parser.add_argument("--quality", type=float, default=1.0, help="quality 0..1 (default 1.0)")
    parser.add_argument("--collaborators", type=int, default=1, help="number of collaborators (splits credit)")
    parser.add_argument("--rare", action="store_true", help="cared for a forgotten page (+50%%)")
    parser.add_argument("--impact", type=int, default=0, help="number of impacted contexts")
    parser.add_argument("--ts", help="event ISO date (YYYY-MM-DD); default today (UTC)")
    parser.add_argument(
        "--events-path",
        type=Path,
        default=EVENTS_PATH,
        help=f"JSONL path (default {EVENTS_PATH.relative_to(ROOT).as_posix()})",
    )

    args = parser.parse_args(argv)
    events_path = Path(args.events_path)
    # Badge/level names in the generated output follow the config language.
    language = CONFIG.language

    if args.add:
        if not (args.event and args.actor and args.context):
            parser.error("--add requires --event, --actor and --context")
        return _add(args, events_path)
    if args.summary:
        return _summary(events_path, language)
    if args.dashboard:
        return _dashboard(events_path, language)
    if args.mirror:
        out = mirror_events(events_path.parent)
        if out is None:
            print(f"no live ledger in {events_path.relative_to(ROOT)} (nothing to mirror)")
            return 0
        print(f"versioned mirror -> {out.relative_to(ROOT)}")
        return 0

    parser.error("provide an action: --add, --summary, --dashboard or --mirror")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
