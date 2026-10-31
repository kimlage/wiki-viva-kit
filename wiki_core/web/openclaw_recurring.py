"""Bounded wake-up through the existing administrative bus; no daemon/task queue.

The configured UTC interval supplies occurrence identity. Retained native effects
and canonical action/proposal state supply all work/recovery state.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from wiki_core.coordination import digest
from wiki_core.openclaw_config import require
from wiki_core.web import openclaw as oc
from wiki_core.web.admin.audit import _audit_settings, _event_hash, audit_log_path


WAKE_SCHEMA_VERSION = "wiki_openclaw_wake.v1"
WAKE_MODES = {"dispatch", "inspect", "unchanged", "already_observed", "review_required",
              "incorporation_required", "reconciliation_required"}
WAKE_ERRORS = {"admin_plan_stale", "admin_plan_already_executed", "admin_plan_sha_mismatch",
               "admin_capability_denied", "admin_session_expired", "admin_session_invalid",
               "admin_confirmation_required", "admin_confirmation_mismatch", "admin_checkout_busy",
               "admin_command_failed", "execution_failed"}
MAX_AUDIT_READ_BYTES = 16_000_000


def wake_summary(content, result):
    """Whitelist an executed tick into the existing command audit event.

    Planning and dry-run entries are not wake execution evidence. A failed
    execution cannot prove that no send happened, so its dispatch is unknown.
    No native text, prompt, route address or credential enters this summary.
    """
    if content.get("command_id") != "agents.openclaw.tick" or content.get("dry_run"):
        return None
    prepared = content.get("diff") or {}
    if (prepared.get("mode") not in WAKE_MODES or type(prepared.get("slot")) is not int
            or not isinstance(prepared.get("rule_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", prepared["rule_sha256"])):
        return None
    output = result.get("output") or {}
    success = result.get("ok") is True
    error = result.get("error_code")
    return json.dumps({"schema_version": WAKE_SCHEMA_VERSION,
        "rule_id": prepared["rule_id"], "rule_sha256": prepared["rule_sha256"],
        "slot": prepared["slot"], "mode": prepared["mode"],
        "effect_key": prepared.get("effect_key"), "status": "success" if success else "failure",
        "new_dispatch": output.get("new_dispatch") is True if success else None,
        "error_code": None if success else error if error in WAKE_ERRORS else "execution_failed"},
        sort_keys=True, separators=(",", ":"))


def latest_wakes(root, config):
    """Read one bounded audit snapshot; expose only verified tick summaries.

    This does not append, repair, compact or acknowledge audit events. The
    first retained hash may point outside the retention window, as in the
    existing verifier. Absence of evidence never proves scheduler liveness.
    """
    settings = _audit_settings(config)
    if not settings["enabled"]:
        return {}, "openclaw_wake_audit_disabled"
    if not settings["hash_chain"]:
        return {}, "openclaw_wake_audit_unverified"
    try:
        path = oc._safe(root, audit_log_path(root, config).relative_to(root).as_posix())
        if not path.exists():
            return {}, "openclaw_wake_not_recorded"
        with path.open("rb") as stream:
            raw = stream.read(MAX_AUDIT_READ_BYTES + 1)
        if len(raw) > MAX_AUDIT_READ_BYTES:
            return {}, "openclaw_wake_audit_too_large"
        # A concurrent append may be incomplete. Do not project a partial
        # receipt; the next independent read can observe the completed line.
        if raw and not raw.endswith(b"\n"):
            return {}, "openclaw_wake_audit_unavailable"
        previous = None
        found = {}
        rules = oc.validated_config(config.openclaw).get("recurring", {})
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if (not isinstance(event, dict) or event.get("event_hash") != _event_hash(event)
                    or previous is not None and event.get("prev_hash") != previous):
                return {}, "openclaw_wake_audit_corrupt"
            previous = event["event_hash"]
            if event.get("command_id") != "agents.openclaw.tick":
                continue
            summary = event.get("output_summary")
            if not isinstance(summary, str) or not summary.startswith("{"):
                continue  # Older generic audit entries have no typed wake.
            wake = json.loads(summary)
            fields = {
                "schema_version", "rule_id", "slot", "mode", "effect_key", "status", "new_dispatch", "error_code"
            }
            require(isinstance(wake, dict) and set(wake) in (fields, fields | {"rule_sha256"})
                    and wake["schema_version"] == WAKE_SCHEMA_VERSION, "openclaw_wake_audit_corrupt")
            if wake["rule_id"] not in rules:
                continue
            # A reused rule ID is not the same action/profile/cadence. Legacy
            # summaries without the plan's binding cannot establish a wake for
            # the current rule; never retrofit their timestamp onto new policy.
            rule_sha = wake.get("rule_sha256")
            if rule_sha is None:
                continue
            require(isinstance(rule_sha, str) and re.fullmatch(r"[a-f0-9]{64}", rule_sha),
                    "openclaw_wake_audit_corrupt")
            if rule_sha != digest(rules[wake["rule_id"]]):
                continue
            require(type(wake["slot"]) is int and wake["slot"] >= 0 and wake["mode"] in WAKE_MODES
                and (wake["effect_key"] is None or isinstance(wake["effect_key"], str)
                     and re.fullmatch(r"wiki-run-[a-f0-9]{32}", wake["effect_key"]))
                and wake["status"] in {"success", "failure"}
                and (type(wake["new_dispatch"]) is bool if wake["status"] == "success" else wake["new_dispatch"] is None)
                and (wake["error_code"] is None if wake["status"] == "success" else wake["error_code"] in WAKE_ERRORS),
                "openclaw_wake_audit_corrupt")
            timestamp_text = event.get("timestamp")
            if not isinstance(timestamp_text, str):
                return {}, "openclaw_wake_audit_corrupt"
            timestamp = dt.datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
            require(timestamp.tzinfo is not None, "openclaw_wake_audit_corrupt")
            found[wake["rule_id"]] = {key: value for key, value in wake.items()
                                      if key not in {"schema_version", "rule_id", "rule_sha256"}}
            found[wake["rule_id"]]["observed_at"] = timestamp.isoformat()
        return found, None if found else "openclaw_wake_not_recorded"
    except (OSError, ValueError, TypeError, KeyError):
        return {}, "openclaw_wake_audit_unavailable"


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
        return {"mode": mode, "rule_id": prepared["rule_id"], "slot": prepared["slot"],
                **oc.inspect(root, config, prepared["query"])}
    if mode != "dispatch":
        return {k: v for k, v in prepared.items() if k not in {"binding", "rule_sha256"}}
    directory = oc._safe(root, prepared["occurrence_path"])
    oc.write_new(directory, {"rule_id": prepared["rule_id"], "slot": prepared["slot"],
        "effect_key": prepared["effect_key"], "plan_sha256": digest(prepared["prepared"])})
    # If this step becomes uncertain, the occurrence remains consumed. Neither
    # a restart nor a newer interval silently replays the send.
    return {"mode": mode, "rule_id": prepared["rule_id"], "slot": prepared["slot"],
            **oc.dispatch(root, config, prepared["prepared"])}
