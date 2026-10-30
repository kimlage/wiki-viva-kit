"""Bounded wake-up through the existing administrative bus; no daemon/task queue.

The configured UTC interval supplies occurrence identity. Retained native effects
and canonical action/proposal state supply all work/recovery state.
"""
from __future__ import annotations

import datetime as dt
from wiki_core.coordination import digest
from wiki_core.openclaw_config import require
from wiki_core.web import openclaw as oc


def now():
    return dt.datetime.now(dt.timezone.utc)


def plan_tick(root, config, params):
    require(set(params) == {"rule_id"}, "openclaw_recurring_rule_required")
    runtime = oc.validated_config(config.openclaw)
    rule_id = params["rule_id"]
    rule = runtime.get("recurring", {}).get(rule_id)
    require(rule is not None, "openclaw_recurring_not_configured")
    b = oc.binding(root, config, rule["profile"], rule["action_id"], admissible=False, require_clean=False)
    slot = int(now().timestamp()) // (rule["interval_minutes"] * 60)
    parent = oc.storage(root, config, "wiki-run-" + "0" * 32).parent
    occurrence = oc._safe(root, (parent / "occurrences" / rule_id / (str(slot) + ".json")).relative_to(root).as_posix())
    base = {"rule_id": rule_id, "slot": slot, "binding": b, "rule_sha256": digest(rule),
            "occurrence_path": occurrence.relative_to(root).as_posix(),
            "canonical_write": False, "new_dispatch": False}
    for file in sorted(occurrence.parent.glob("*.json")):
        claim = oc.read_receipt(file)
        effect = claim.get("effect_key")
        directory = oc.storage(root, config, effect)
        if not (directory / "intent.json").exists():
            return {**base, "mode": "reconciliation_required", "effect_key": effect}
    # Inspect a retained effect first, regardless of the current interval. A
    # completed return still waits for reviewed incorporation before new work.
    old = []
    for file in sorted(parent.glob("wiki-run-*/intent.json")):
        intent = oc.read_receipt(file)
        plan = intent.get("plan", {})
        if plan.get("recurrence", {}).get("rule_id") != rule_id:
            continue
        require(intent.get("plan_sha256") == digest(plan), "openclaw_intent_changed")
        query = {"profile": rule["profile"], "action_id": rule["action_id"], "effect_key": plan["effect_key"]}
        directory, _, _, _ = oc.retained_intent(root, config, query)
        if not (directory / "result.json").exists() and not (directory / "failure-resolution.json").exists():
            return {**base, "mode": "inspect", "query": query, "effect_key": plan["effect_key"]}
        if (directory / "failure-resolution.json").exists():
            oc.verified_failure_resolution(directory, plan, root)
        else:
            proposal = oc.proposal_status(root, config, directory, plan)
            if not proposal or proposal["status"] != "received_in_main":
                return {**base, "mode": "review_required", "effect_key": plan["effect_key"]}
            if not proposal.get("content_incorporated_in_main"):
                return {**base, "mode": "incorporation_required", "effect_key": plan["effect_key"]}
        old.append(plan)
    if occurrence.exists():
        claim = oc.read_receipt(occurrence)
        require(claim.get("rule_id") == rule_id and claim.get("slot") == slot,
                "openclaw_occurrence_changed")
        return {**base, "mode": "already_observed", "effect_key": claim["effect_key"]}
    paths = set()
    for ref in rule["watch_paths"]:
        # Git owns selection. No globs, external files, ignored caches or source
        # dates are expanded into a new source access grant.
        require(not any(c in ref for c in ":*?[\\"), "openclaw_invalid_watch_path")
        raw = oc.git(root, "ls-tree", "-r", "HEAD", "--", ref)
        require(bool(raw), "openclaw_watch_path_missing")
        paths.update(raw.splitlines())
    watched = digest(sorted(paths))
    if old and max(old, key=lambda p: p["recurrence"]["slot"])["recurrence"]["watched_sha256"] == watched:
        return {**base, "mode": "unchanged", "watched_sha256": watched}
    message = rule["message"].replace("{approved_head}", b["base_head"])
    message += f"\n\nCanonical occurrence: {rule_id}/{slot}. Approved revision: {b['base_head']}."
    prepared = oc.plan_dispatch(root, config, {"profile": rule["profile"], "action_id": rule["action_id"],
        "action_sha256": b["action_sha256"], "mission_id": rule["mission_id"], "message": message})
    prepared["recurrence"] = {"rule_id": rule_id, "slot": slot, "watched_sha256": watched,
                              "occurrence_path": base["occurrence_path"]}
    return {**base, "mode": "dispatch", "prepared": prepared,
            "effect_key": prepared["effect_key"], "watched_sha256": watched}


def execute_tick(root, config, params, prepared):
    require(plan_tick(root, config, params) == prepared, "openclaw_recurring_inputs_changed")
    mode = prepared["mode"]
    if mode == "inspect":
        return {"mode": mode, **oc.inspect(root, config, prepared["query"])}
    if mode != "dispatch":
        return {k: v for k, v in prepared.items() if k not in {"binding", "rule_sha256"}}
    directory = oc._safe(root, prepared["occurrence_path"])
    oc.write_new(directory, {"rule_id": prepared["rule_id"], "slot": prepared["slot"],
        "effect_key": prepared["effect_key"], "plan_sha256": digest(prepared["prepared"])})
    # If this step becomes uncertain, the occurrence remains consumed. Neither
    # a restart nor a newer interval silently replays the send.
    return {"mode": mode, **oc.dispatch(root, config, prepared["prepared"])}
