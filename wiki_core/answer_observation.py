"""Opt-in notification of a committed human answer to a local consumer.

This is transport over canonical dialogue, not a runner, permission grant or
queue. The consumer owns deduplication, STOP, lineage, unblock CAS and recovery.
No snapshot rebuild or model call is needed to capture one persisted answer.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from wiki_core.action_dialogue import EVENT_ID, validate_history
from wiki_core.action_transition import (
    ActionTransitionError, _action_file_lock, _assert_no_secrets,
    _contained_action_path, _parse_document, _receipt_id, _receipt_entry_error,
    _parsed_transition_instant,
    _governed_support_sha256, _governed_support_value,
)
from wiki_core.config import load_config
from wiki_core.coordination import CoordinationError, POLICY_FILE, _read, load_policy

SCHEMA = "wiki_canonical_answer_observation.v1"


class AnswerObservationError(ValueError):
    pass


def validate_canonical_answer_payload(frontmatter: dict[str, Any], event_id: str,
                                      receipt_id: str) -> None:
    """Pure check of retained answer bytes against canonical transition hashes.

    Requires the actual parsed canonical action, never an HTTP-supplied copy.
    No I/O, lock, transport or authority grant. The caller owns a stable source
    read, profile/lineage/STOP checks and its own atomic unblock boundary.
    Raises AnswerObservationError (or ValueError for malformed dialogue).
    """
    fm = frontmatter
    if fm.get("page_type") != "action":
        raise AnswerObservationError("not_a_canonical_action")
    events = fm.get("action_dialogue") or []
    validate_history(events)
    matches = [e for e in events if e["event_id"] == event_id]
    if len(matches) != 1 or matches[0]["kind"] != "answer" or matches[0]["actor"] != "operator":
        raise AnswerObservationError("canonical_operator_answer_required")
    event = matches[0]
    history = fm.get("action_state_history") or []
    if not isinstance(history, list) or any(not isinstance(e, dict) for e in history):
        raise AnswerObservationError("invalid_transition_history")
    previous = None
    for row in history:
        error = _receipt_entry_error(row, expected_from=previous["to"] if previous else str(row.get("from") or ""),
            expected_page_id=str(fm.get("page_id") or ""),
            expected_prior_receipt_id=previous["receipt_id"] if previous else "",
            expected_first_revision=None,
            expected_prior_at=_parsed_transition_instant(previous["at"]) if previous else None)
        if error:
            raise AnswerObservationError("invalid_transition_lineage")
        previous = row
    entries = [(i, e) for i, e in enumerate(history) if e.get("receipt_id") == receipt_id]
    if len(entries) != 1:
        raise AnswerObservationError("canonical_receipt_missing")
    index, entry = entries[0]
    if (entry.get("receipt_id") != _receipt_id(entry) or entry.get("page_id") != fm.get("page_id")
        or entry.get("before_sha256") != event["before_sha256"] or entry.get("at") != event["at"]
        or "action_dialogue" not in (entry.get("support_fields") or [])):
        raise AnswerObservationError("answer_transition_binding_mismatch")
    # Receipt IDs bind hashes, not the current event text. Verify the
    # original payload, including the entire question/answer prefix. A
    # later receipt cannot legitimize a rewritten historical answer.
    if history[-1]["governed_support_sha256"] != _governed_support_sha256(
            fm, schema_version=history[-1]["schema_version"]):
        raise AnswerObservationError("current_support_binding_mismatch")
    fields = entry["support_fields"]
    subsequent_fields = {field for row in history[index + 1:] for field in row["support_fields"]}
    if (set(fields) - {"action_dialogue"}) & subsequent_fields:
        # Old values are not retained in this bounded receipt chain.
        # Refuse rather than infer them from newer support values.
        raise AnswerObservationError("original_answer_support_not_retained")
    event_index = events.index(event)
    support = {field: events[:event_index + 1] if field == "action_dialogue"
               else _governed_support_value(fm, field) for field in fields}
    payload = json.dumps({"reason": entry.get("reason", ""), "support": support},
                         ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if hashlib.sha256(payload.encode()).hexdigest() != entry["payload_sha256"]:
        raise AnswerObservationError("answer_payload_binding_mismatch")


def _capture(root: Path, page_ref: str, event_id: str, receipt: dict[str, Any],
             *, reconciliation: bool) -> tuple[dict, dict, str]:
    config = load_config(root)
    policy = load_policy(root)
    if not policy:
        raise AnswerObservationError("coordinator_mapping_unavailable")
    path, page_ref = _contained_action_path(root, page_ref)
    with _action_file_lock(root, page_ref):
        raw = path.read_text(encoding="utf-8")
        fm, _ = _parse_document(raw)
        if fm.get("page_type") != "action":
            raise AnswerObservationError("not_a_canonical_action")
        validate_canonical_answer_payload(fm, event_id, receipt.get("receipt_id"))
        events = fm["action_dialogue"]
        event = next(e for e in events if e["event_id"] == event_id)
        profile = policy[0]["profiles"].get(event["coordinator"])
        if not profile or fm.get("page_id") not in profile.get("action_ids", []):
            raise AnswerObservationError("coordinator_route_changed")
        history = fm["action_state_history"]
        index = next(i for i, e in enumerate(history) if e["receipt_id"] == receipt["receipt_id"])
        if reconciliation:
            if set(receipt) != {"receipt_id"}:
                raise AnswerObservationError("reconciliation_receipt_id_only")
            source = {"kind": "wiki_canonical_answer_reconciliation",
                      "coverage": "canonical_event_and_transition_lineage"}
        else:
            if (receipt.get("changed") is not True or receipt.get("idempotent") is not False
                or receipt.get("page_id") != fm.get("page_id") or receipt.get("page_ref") != page_ref
                or receipt.get("before_sha256") != event["before_sha256"]
                or receipt.get("recorded_at") != event["at"]):
                raise AnswerObservationError("original_append_receipt_required")
            after = receipt.get("after_sha256")
            current = hashlib.sha256(raw.encode()).hexdigest()
            # A later canonical suffix can retain the original exact post-write
            # hash as its first before_sha256. Never fabricate an after hash.
            if current != after and (index + 1 >= len(history) or history[index + 1].get("before_sha256") != after):
                raise AnswerObservationError("original_after_revision_not_retained")
            source = {"kind": "wiki_cockpit_action_transition", "route": "/api/actions/transition"}
        envelope = {"schema_version": SCHEMA,
                    "task_ref": {"repo_id": config.repo_id, "action_id": fm["page_id"]},
                    "profile": event["coordinator"], "event": dict(event),
                    "receipt": dict(receipt), "source": source}
        _assert_no_secrets(json.dumps(envelope, ensure_ascii=False, allow_nan=False))
        return envelope, profile, policy[1]


def _observer(profile: dict) -> tuple[list[str], int] | None:
    value = profile.get("answer_observer")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"argv", "timeout_seconds"}:
        raise AnswerObservationError("invalid_answer_observer")
    argv, timeout = value.get("argv"), value.get("timeout_seconds", 10)
    if (not isinstance(argv, list) or not argv or len(argv) > 32
        or any(not isinstance(x, str) or not x or len(x) > 2000 or "\x00" in x for x in argv)
        or any(x == "--event-file" or x.startswith("--event-file=") for x in argv)
        or not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 30):
        raise AnswerObservationError("invalid_answer_observer")
    _assert_no_secrets(json.dumps(argv, ensure_ascii=False))
    return argv, timeout


def observe_canonical_answer(root: Path, page_ref: str, event_id: str,
                             receipt: dict[str, Any], *, reconciliation: bool = False,
                             active_policy_sha256: str | None = None) -> dict:
    """Notify one configured consumer after commit; failure never rolls it back.

    Immediate receipt is the actual in-memory append result. Reconciliation
    supplies only its retained receipt_id, and makes no HTTP/afterSHA claim.
    No original receipt is reconstructed by re-running a transition.
    """
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id) or not isinstance(receipt, dict):
        return {"status": "refused", "answer_committed": False, "error": "invalid_answer_observation_input",
                "model_started_by_wiki": False, "authority_created": False}
    result = {"status": "unknown", "answer_committed": False, "event_id": event_id,
              "model_started_by_wiki": False, "authority_created": False}
    try:
        envelope, profile, policy_sha = _capture(root, page_ref, event_id, receipt,
                                                reconciliation=reconciliation)
        result["answer_committed"] = True
        result["task_ref"] = envelope["task_ref"]
        observer = _observer(profile)
        if observer is None:
            return {**result, "status": "not_configured"}
        if not active_policy_sha256:
            return {**result, "status": "not_configured", "error": "observer_not_activated"}
        if active_policy_sha256 != policy_sha:
            raise AnswerObservationError("observer_policy_requires_reactivation")
        argv, timeout = observer
        # Only the consumer-owned trusted policy selects a command. No card,
        # request text, nonce or claimed principal is evaluated as code.
        if hashlib.sha256(_read(root, POLICY_FILE)).hexdigest() != policy_sha:
            raise AnswerObservationError("observer_policy_changed")
        with tempfile.TemporaryDirectory(prefix="wiki-answer-") as directory:
            event_file = Path(directory) / "event.json"
            with event_file.open("x", encoding="utf-8") as handle:
                os.chmod(event_file, 0o600)
                json.dump(envelope, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
            # Never retain stdout/tool histories as a second task journal.
            with tempfile.TemporaryFile() as output:
                completed = subprocess.run([*argv, "--event-file", str(event_file)], cwd=root,
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=timeout, check=False)
                size = output.tell()
                output.seek(0)
                raw = output.read(65_537)
            if size > 65_536:
                return {**result, "error": "observer_output_limit"}
            result["output_sha256"] = hashlib.sha256(raw).hexdigest()
            result["exit_code"] = completed.returncode
            try:
                response = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                return {**result, "error": "observer_ack_unavailable"}
            if not isinstance(response, dict):
                return {**result, "error": "observer_ack_unavailable"}
            _assert_no_secrets(json.dumps(response, allow_nan=False))
            if response.get("event_id") != event_id or response.get("task_ref") != envelope["task_ref"]:
                return {**result, "error": "observer_ack_binding_mismatch"}
            status = response.get("status")
            unblocked = response.get("unblocked")
            if (status not in {"resumed", "observed", "held", "refused"}
                or not isinstance(unblocked, bool) or response.get("model_started") is not False
                or unblocked != (status == "resumed")):
                return {**result, "error": "observer_ack_protocol_mismatch"}
            result.update(consumer_status=status, unblocked=unblocked)
            if status == "refused" and response.get("ok") is False:
                return {**result, "status": "refused", "error": "observer_did_not_accept"}
            if completed.returncode != 0 or response.get("ok") is not True:
                return {**result, "error": "observer_outcome_unknown"}
            return {**result, "status": "delivered"}
    except subprocess.TimeoutExpired:
        return {**result, "error": "observer_timeout_delivery_unknown"}
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        safe = str(exc) if isinstance(exc, (AnswerObservationError, CoordinationError)) else "observer_unavailable"
        return {**result, "status": "refused" if isinstance(exc, (AnswerObservationError, CoordinationError, ActionTransitionError)) else "unknown",
                "error": safe}
