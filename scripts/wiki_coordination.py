#!/usr/bin/env python3
"""Read canonical coordinator routes or prepare revision-bound agent context."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from _common import ROOT
from wiki_core.config import load_config
from wiki_core.coordination import coordination_index, context_packet, validate_dialogue_route
from wiki_core.action_transition import transition_action_page
from wiki_core.web.snapshot import build_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile")
    parser.add_argument("--action-id")
    parser.add_argument("--event-file", type=Path, help="Append one dialogue event from a JSON file (trusted local adapter).")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--as-operator", action="store_true", help="Record an operator event rather than a coordinator event.")
    args = parser.parse_args()
    if args.event_file and (not args.profile or not args.action_id or not args.expected_sha256):
        parser.error("--event-file requires --profile, --action-id and --expected-sha256")
    if (args.expected_sha256 or args.as_operator) and not args.event_file:
        parser.error("write options require --event-file")
    if args.action_id and not args.profile:
        parser.error("--action-id requires --profile")
    root = args.root.resolve()
    config = load_config(root)
    snapshot = build_snapshot(root, config)
    result = context_packet(root, config, snapshot, args.profile, args.action_id) if args.profile else coordination_index(root, snapshot)
    if args.event_file:
        if args.event_file.stat().st_size > 16_000:
            parser.error("event file exceeds limit")
        event = json.loads(args.event_file.read_text())
        if not isinstance(event, dict) or event.get("coordinator") != args.profile:
            parser.error("event coordinator must equal selected profile")
        action = result["actions"][0]
        validate_dialogue_route(root, action["path"], event)
        result = transition_action_page(root, action["path"], action["state"],
            expected_sha256=args.expected_sha256, dialogue_event=event,
            dialogue_actor="operator" if args.as_operator else "coordinator:" + args.profile,
            next_action=event.get("text") if event.get("kind") == "direction" else None).to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
