"""Materialized admin plans: plan -> review -> execute (god-mode plan §9, §11).

A plan is an immutable, server-side description of exactly what one command
invocation will do: summary, preconditions, effects, diff (when applicable),
validation, undo strategy and the confirmation the risk level demands. The
``plan_sha`` is a SHA-256 over the canonical plan content, so the execute
request can only ever run **what was reviewed** — a tampered sha, a mutated
worktree, a switched branch, a changed config or a revoked capability all
refuse execution with a typed error and force a replan (§9.3).

Everything here delegates to EXISTING repo paths: the allowlisted ActionCard
catalog (``run_action``), the snapshot derive path (``write_snapshot``) and
``load_config``. No planner or executor ever receives argv from the browser,
and no new subprocess surface is introduced beyond fixed git read commands.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.admin.audit import redact_audit_value
from wiki_core.web.admin.capabilities import admin_health_summary
from wiki_core.web.admin.commands import (
    AdminCommandSpec,
    command_capabilities_granted,
)
from wiki_core.web.admin.sessions import AdminSessionManager
from wiki_core.web.commands import (
    RISK_LEVEL_DERIVE,
    RISK_LEVEL_DESTRUCTIVE,
    RISK_LEVEL_EXTERNAL_WRITE,
    RISK_LEVEL_PROPOSAL_WRITE,
    RISK_LEVEL_READ,
    redact_secret_values,
    run_action,
)
from wiki_core.web.git_workflows import CHECKOUT_LOCK
from wiki_core.web.schemas import SNAPSHOT_FILES
from wiki_core.web.snapshot import snapshot_publication_status, write_snapshot

ADMIN_PLAN_SCHEMA_VERSION = "wiki_admin_plan.v1"

# A plan is a short-lived review artifact, not a job queue: reviewing takes
# minutes, and anything older must be replanned against current reality.
PLAN_TTL_S = 600
MAX_PLANS = 64

# Typed refusal vocabulary (closed set — the frontend mirrors it).
ERROR_UNKNOWN_COMMAND = "admin_unknown_command"
ERROR_INVALID_PARAMS = "admin_invalid_params"
ERROR_CAPABILITY_DENIED = "admin_capability_denied"
ERROR_PLAN_NOT_FOUND = "admin_plan_not_found"
ERROR_PLAN_SHA_MISMATCH = "admin_plan_sha_mismatch"
ERROR_PLAN_STALE = "admin_plan_stale"


def _proposal_error_code(code: str) -> str:
    if code.startswith("admin_"):
        return code
    if code in {"proposal_material_digest_mismatch", "proposal_planned_readset_changed",
                "proposal_generated_material_changed", "proposal_action_revision_mismatch",
                "proposal_document_preimage_mismatch", "proposal_base_or_branch_mismatch",
                "proposal_git_base_changed", "proposal_readset_changed"}:
        return ERROR_PLAN_STALE
    return "admin_command_failed"
ERROR_PLAN_ALREADY_EXECUTED = "admin_plan_already_executed"
ERROR_CONFIRMATION_REQUIRED = "admin_confirmation_required"
ERROR_CONFIRMATION_MISMATCH = "admin_confirmation_mismatch"
ERROR_CHECKOUT_BUSY = "admin_checkout_busy"
ERROR_COMMAND_FAILED = "admin_command_failed"


# ---------------------------------------------------------------------------
# deterministic environment fingerprints (§9.3 preconditions)
# ---------------------------------------------------------------------------


def _constant_time_eq(supplied: str, expected: str) -> bool:
    """Constant-time string equality that never raises on non-ASCII input."""

    return hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    )


def _run_git(root: Path, args: list[str]) -> tuple[int, str]:
    """Run one fixed read-only git command (same shape as git_ops)."""

    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout


def current_branch(root: Path) -> str:
    code, output = _run_git(root, ["branch", "--show-current"])
    return output.strip() if code == 0 else ""


def _derived_prefix(config: WikiConfig) -> str:
    return str(config.paths.get("derived_root") or "data/derived/wiki").rstrip("/") + "/"


def worktree_fingerprint(root: Path, config: WikiConfig) -> str:
    """Opaque digest over HEAD plus the AUTHORED dirty set.

    Derived caches (``derived_root``, which includes the admin audit trail and
    the web snapshot itself) are rebuildable outputs, not reviewed content, so
    they are excluded — otherwise writing the plan's own audit event would
    make every plan instantly stale. File names never leave this function:
    only the hash is stored on the plan.
    """

    head_code, head = _run_git(root, ["rev-parse", "HEAD"])
    status_code, status = _run_git(
        root, ["status", "--porcelain=v1", "--untracked-files=all"]
    )
    digest = hashlib.sha256()
    digest.update((head.strip() if head_code == 0 else "no-head").encode("utf-8"))
    digest.update(b"\0")
    if status_code != 0:
        digest.update(b"status-unavailable\0")
        return "sha256:" + digest.hexdigest()
    prefix = _derived_prefix(config)
    kept: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path_field = line[3:]
        paths = path_field.split(" -> ") if " -> " in path_field else [path_field]
        if all(path.strip('"').startswith(prefix) for path in paths):
            continue
        kept.append(line)
    for line in sorted(kept):
        digest.update(line.encode("utf-8"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def config_fingerprint(root: Path) -> str:
    """Digest over every root-level ``wiki*.yaml``/``wiki*.yml`` file — the
    same closed family the live snapshot revision watches."""

    digest = hashlib.sha256()
    try:
        names = sorted(
            entry
            for entry in os.listdir(root)
            if entry.lower().startswith("wiki")
            and entry.lower().endswith((".yaml", ".yml"))
        )
    except OSError:
        names = []
        digest.update(b"root-scan-error\0")
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            digest.update(b"unreadable")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _snapshot_dir(root: Path, config: WikiConfig) -> Path:
    return WikiPaths(root, config).derived_root / "web-snapshot"


# ---------------------------------------------------------------------------
# planners — pure descriptions of what an execution WOULD do
# ---------------------------------------------------------------------------


def _effects(
    *,
    files_read: list[str] | None = None,
    files_write: list[str] | None = None,
    external_calls: list[str] | None = None,
    snapshot_invalidated: bool = False,
) -> dict[str, Any]:
    return {
        "files_read": list(files_read or ()),
        "files_write": list(files_write or ()),
        "external_calls": list(external_calls or ()),
        "snapshot_invalidated": snapshot_invalidated,
    }


def _no_undo() -> dict[str, Any]:
    return {"kind": None, "available": False}


def _plan_system_inspect(
    root: Path, config: WikiConfig, params: dict[str, str], dry_run: bool
) -> dict[str, Any]:
    return {
        "summary": (
            "Read-only inspection of repository, operator and snapshot "
            "publication state. Nothing is written."
        ),
        "effects": _effects(files_read=[".git", "wiki.config.yaml"]),
        "diff": None,
        "validation": {"kind": "none"},
        "undo": _no_undo(),
        "targets": [],
    }


def _plan_config_inspect(
    root: Path, config: WikiConfig, params: dict[str, str], dry_run: bool
) -> dict[str, Any]:
    return {
        "summary": (
            "Read the effective configuration as parsed from wiki.config.yaml. "
            "Nothing is written; secret-shaped keys cannot exist here by "
            "construction (config parsing fails closed on them)."
        ),
        "effects": _effects(files_read=["wiki.config.yaml"]),
        "diff": None,
        "validation": {"kind": "none"},
        "undo": _no_undo(),
        "targets": ["wiki.config.yaml"],
    }


def _plan_config_validate(
    root: Path, config: WikiConfig, params: dict[str, str], dry_run: bool
) -> dict[str, Any]:
    return {
        "summary": (
            "Re-parse wiki.config.yaml strictly and report whether it is "
            "valid. Validation writes nothing — an invalid file is a report, "
            "never a mutation."
        ),
        "effects": _effects(files_read=["wiki.config.yaml"]),
        "diff": None,
        "validation": {"kind": "config_parse", "target": "wiki.config.yaml"},
        "undo": _no_undo(),
        "targets": ["wiki.config.yaml"],
    }


def _plan_snapshot_rebuild(
    root: Path, config: WikiConfig, params: dict[str, str], dry_run: bool
) -> dict[str, Any]:
    out_dir = _snapshot_dir(root, config)
    try:
        rel_dir = out_dir.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - derived_root is always inside root
        rel_dir = "data/derived/wiki/web-snapshot"
    publication = snapshot_publication_status(
        root, out_dir, repo_id=config.repo_id
    )
    previous_revision = publication.get("active_revision")
    if dry_run:
        summary = (
            "Dry run: list the snapshot files a rebuild would publish. "
            "Nothing is written."
        )
    else:
        summary = (
            "Rebuild the derived web snapshot through the existing "
            "publication path (immutable revision + active pointer) and "
            "invalidate the live cache."
        )
    return {
        "summary": summary,
        "effects": _effects(
            files_read=["memories", "wiki.config.yaml"],
            files_write=[] if dry_run else [rel_dir],
            snapshot_invalidated=not dry_run,
        ),
        "diff": None,
        "validation": {"kind": "deterministic_rebuild"},
        "undo": {
            "kind": "restore_previous_snapshot_revision",
            "available": bool(previous_revision) and not dry_run,
            "previous_revision": previous_revision,
            "previous_snapshot_id": publication.get("active_snapshot_id"),
        },
        "targets": [],
    }


# ---------------------------------------------------------------------------
# executors — the only code that runs on execute; all reuse existing paths
# ---------------------------------------------------------------------------


def _execute_system_inspect(
    root: Path, config: WikiConfig, dry_run: bool
) -> dict[str, Any]:
    # Reuses the allowlisted `git-status` ActionCard from the operator
    # catalog (wiki_web_actions.v1) — output already redacted by run_action.
    git_result = run_action(root, config, "git-status", dry_run=False)
    publication = snapshot_publication_status(
        root, _snapshot_dir(root, config), repo_id=config.repo_id
    )
    return {
        "output": {
            "admin": admin_health_summary(config),
            "branch": current_branch(root),
            "git_status": {
                "ok": git_result.get("ok", False),
                "results": [
                    {
                        "ok": item.get("ok"),
                        "stdout": item.get("stdout", ""),
                        "stderr": item.get("stderr", ""),
                    }
                    for item in git_result.get("results", ())
                ],
            },
            "publication": {
                "layout": publication.get("layout"),
                "active_revision": publication.get("active_revision"),
                "active_snapshot_id": publication.get("active_snapshot_id"),
            },
        },
        "affected_paths": [],
        "snapshot_invalidated": False,
    }


def _execute_config_inspect(
    root: Path, config: WikiConfig, dry_run: bool
) -> dict[str, Any]:
    fresh = load_config(root)
    return {
        "output": {
            "repo_id": fresh.repo_id,
            "default_context": fresh.default_context,
            "admin": dict(fresh.admin),
            "features": dict(fresh.features),
        },
        "affected_paths": [],
        "snapshot_invalidated": False,
    }


def _execute_config_validate(
    root: Path, config: WikiConfig, dry_run: bool
) -> dict[str, Any]:
    try:
        fresh = load_config(root)
    except Exception as exc:  # noqa: BLE001 - the invalid config IS the report
        return {
            "output": {
                "valid": False,
                "error": redact_secret_values(str(exc)),
            },
            "affected_paths": [],
            "snapshot_invalidated": False,
        }
    return {
        "output": {
            "valid": True,
            "repo_id": fresh.repo_id,
            "matches_running_operator": fresh == config,
        },
        "affected_paths": [],
        "snapshot_invalidated": False,
    }


def _execute_snapshot_rebuild(
    root: Path, config: WikiConfig, dry_run: bool
) -> dict[str, Any]:
    out_dir = _snapshot_dir(root, config)
    try:
        rel_dir = out_dir.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - derived_root is always inside root
        rel_dir = "data/derived/wiki/web-snapshot"
    if dry_run:
        return {
            "output": {
                "dry_run": True,
                "target_dir": rel_dir,
                "would_write": sorted(SNAPSHOT_FILES),
                "written": [],
            },
            "affected_paths": [],
            "snapshot_invalidated": False,
        }
    # Undo is MATERIALIZED at execute time: the revision that was active
    # immediately before this write is what a restore would point back to.
    prior = snapshot_publication_status(root, out_dir, repo_id=config.repo_id)
    written = write_snapshot(
        root, out_dir, config, clean=True, mode="local_operator"
    )
    return {
        "output": {
            "dry_run": False,
            "target_dir": rel_dir,
            "snapshot_id": getattr(written, "snapshot_id", None),
            "active_revision": getattr(written, "active_revision", None),
            "files": sorted(written),
        },
        "affected_paths": [rel_dir],
        "snapshot_invalidated": True,
        "undo": {
            "kind": "restore_previous_snapshot_revision",
            "available": bool(prior.get("active_revision")),
            "previous_revision": prior.get("active_revision"),
            "previous_snapshot_id": prior.get("active_snapshot_id"),
        },
    }


_PLANNERS: dict[str, Callable[[Path, WikiConfig, dict[str, str], bool], dict[str, Any]]] = {
    "system_inspect": _plan_system_inspect,
    "config_inspect": _plan_config_inspect,
    "config_validate": _plan_config_validate,
    "snapshot_rebuild": _plan_snapshot_rebuild,
}

_EXECUTORS: dict[str, Callable[[Path, WikiConfig, bool], dict[str, Any]]] = {
    "system_inspect": _execute_system_inspect,
    "config_inspect": _execute_config_inspect,
    "config_validate": _execute_config_validate,
    "snapshot_rebuild": _execute_snapshot_rebuild,
}


# ---------------------------------------------------------------------------
# plan materialization
# ---------------------------------------------------------------------------


def _canonical(content: dict[str, Any]) -> str:
    return json.dumps(
        content, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def plan_sha_for(content: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


def _validate_params(
    schema: dict[str, Any], params: dict[str, Any]
) -> str | None:
    if not isinstance(params, dict):
        return "params must be an object"
    for key, value in params.items():
        meta = schema.get(str(key))
        if meta is None:
            return f"unexpected parameter: {key}"
        if not isinstance(value, str):
            return f"parameter {key} must be a string"
        allowed = meta.get("values")
        if allowed and value not in allowed:
            return f"invalid value for parameter {key}"
    for key, meta in schema.items():
        if meta.get("required") and key not in params:
            return f"missing parameter: {key}"
    return None


def _confirmation_spec(spec: AdminCommandSpec, effects: dict[str, Any]) -> dict[str, Any]:
    """§9 policy: reads confirm nothing; a derive that writes confirms with
    the exact plan-generated phrase (button); every proposal/external/
    destructive write demands the TYPED phrase. Never a global phrase."""

    writes = bool(
        effects.get("files_write")
        or effects.get("external_calls")
        or effects.get("snapshot_invalidated")
    )
    if spec.risk_level == RISK_LEVEL_READ or not writes:
        return {"kind": "none", "text": None}
    if spec.risk_level == RISK_LEVEL_DERIVE:
        return {"kind": "simple", "text": f"RUN {spec.id}"}
    if spec.risk_level == RISK_LEVEL_PROPOSAL_WRITE:
        return {"kind": "typed", "text": f"PROPOSE {spec.id}"}
    if spec.risk_level == RISK_LEVEL_EXTERNAL_WRITE:
        return {"kind": "typed", "text": f"PUBLISH {spec.id}"}
    if spec.risk_level == RISK_LEVEL_DESTRUCTIVE:
        return {"kind": "typed", "text": f"REVERT {spec.id}"}
    return {"kind": "typed", "text": f"RUN {spec.id}"}


def build_admin_plan(
    root: Path,
    config: WikiConfig,
    spec: AdminCommandSpec,
    *,
    params: dict[str, Any],
    session: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """Materialize one reviewable plan (§11.2) or a typed refusal."""

    granted, reason = command_capabilities_granted(config, spec, session)
    if not granted:
        return {"ok": False, "error_code": ERROR_CAPABILITY_DENIED, "reason": reason}
    problem = _validate_params(spec.parameter_schema, params)
    if problem is not None:
        return {"ok": False, "error_code": ERROR_INVALID_PARAMS, "detail": problem}
    if dry_run and not spec.supports_dry_run:
        return {
            "ok": False,
            "error_code": ERROR_INVALID_PARAMS,
            "detail": "command does not support dry run",
        }
    if spec.planner == "proposal_adopt":
        from wiki_core.web.normal_proposal import adoption_target
        try:
            target = adoption_target(root, config, params)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error_code": ERROR_INVALID_PARAMS, "detail": getattr(exc, "code", "proposal_adoption_failed")}
        planned = {"summary": "Preserve the proposal branch and fast-forward the clean approved checkout to the displayed commit",
                   "effects": {"files_read": [], "files_write": [] if dry_run else ["approved checkout"],
                               "external_calls": [] if dry_run else ["git fetch origin"], "snapshot_invalidated": not dry_run},
                   "targets": [], "diff": target}
    elif spec.planner in {"proposal_publish", "proposal_promote"}:
        if spec.planner == "proposal_publish":
            from wiki_core.action_transition import _assert_no_secrets
            try:
                _, branch = _run_git(root, ["branch", "--show-current"])
                for value in (params.get("title", ""), params.get("body", ""), branch):
                    _assert_no_secrets(value)
            except ValueError:
                return {"ok": False, "error_code": ERROR_INVALID_PARAMS,
                        "detail": "publication inputs contain an access-secret finding"}
        code, head = _run_git(root, ["rev-parse", "HEAD"])
        if code or params.get("expected_head") != head.strip():
            return {"ok": False, "error_code": ERROR_PLAN_STALE, "failed_preconditions": ["expected_head"]}
        if spec.planner == "proposal_promote":
            from wiki_core.web.normal_proposal import promotion_review
            try:
                promotion_review(root, config, dict(params))
            except (ValueError, OSError, TypeError):
                return {"ok": False, "error_code": ERROR_INVALID_PARAMS,
                        "detail": "promotion requires the current independent review and existing promotion policy"}
        planned = {
            "summary": "One exact-head provider operation" if spec.planner == "proposal_publish" else
                       "Recheck existing policy gates, then ready/merge the independently reviewed exact head",
            "effects": {"files_read": [], "files_write": [],
                        "external_calls": [] if dry_run else [str(params.get("operation") or "reviewed_pr_promotion")],
                        "snapshot_invalidated": not dry_run},
            "targets": [], "diff": {"expected_head": params["expected_head"]},
        }
    elif spec.planner in {"openclaw_dispatch", "openclaw_inspect", "openclaw_receipt", "openclaw_resolve_failed"}:
        from wiki_core.web.openclaw import plan_dispatch, retained_intent, storage, receipt_source, plan_failure_resolution
        try:
            if spec.planner == "openclaw_dispatch":
                prepared = plan_dispatch(root, config, params)
                effect = prepared["effect_key"]
                diff = prepared
            else:
                directory, prepared, _, _ = retained_intent(root, config, params)
                if spec.planner == "openclaw_receipt":
                    _, _, receipt = receipt_source(root, config, params)
                effect = prepared["effect_key"]
                diff = {"action_id": params["action_id"], "effect_key": effect,
                        "message_sha256": prepared["message_sha256"], "new_dispatch": False}
                if spec.planner == "openclaw_resolve_failed":
                    diff = plan_failure_resolution(root, config, params)
                if spec.planner == "openclaw_receipt":
                    diff["result"] = receipt
                    from wiki_core.web.git_workflows import _proposal_branch
                    diff["proposal_branch"] = _proposal_branch(config, "runtime-return-" + effect.removeprefix("wiki-run-")) if current_branch(root) == str(config.approval.get("default_branch") or "main") else current_branch(root)
            directory = storage(root, config, effect)
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error_code": ERROR_INVALID_PARAMS,
                    "detail": getattr(exc, "code", "openclaw_precondition_failed")}
        dispatching = spec.planner == "openclaw_dispatch"
        planned = {
            "summary": "Resolve this failed attempt from preserved independently reviewed evidence; no result, task completion or automatic retry; external effects remain outside this receipt" if spec.planner == "openclaw_resolve_failed" else
                       "Start a proposal branch if on main and derive receipt material; canonical incorporation requires the existing proposal command" if spec.planner == "openclaw_receipt" else
                       "Send the displayed message for this action once; receipt is not completion" if dispatching else
                       "Recover the exact existing run; never dispatch or mark the action done",
            "effects": {"files_read": [prepared["binding"]["action_path"]] + ([params["review_path"], diff["review"]["evidence_path"]] if spec.planner == "openclaw_resolve_failed" else []),
                        "files_write": [] if dry_run else [str(directory.relative_to(root))],
                        "external_calls": [] if dry_run or spec.planner == "openclaw_receipt" else ["OpenClaw chat.send" if dispatching else "OpenClaw chat.history"],
                        "snapshot_invalidated": False},
            "diff": diff, "targets": [prepared["binding"]["action_path"]],
            "validation": {"canonical_write": False, "documentary_integration": "separate reviewed proposal"},
        }
    elif spec.planner == "normal_proposal":
        from wiki_core.web.normal_proposal import ProposalError, preview_proposal
        try:
            preview = preview_proposal(root, config, dict(params))
        except (ValueError, OSError, TypeError) as exc:
            return {"ok": False, "error_code": ERROR_INVALID_PARAMS,
                    "detail": str(exc) if isinstance(exc, ProposalError) else "invalid proposal material"}
        planned = {
            "summary": "Prepare the exact documentary proposal; publication and approval remain separate",
            "effects": {"files_read": sorted(preview["readset"]),
                        "files_write": [] if dry_run else sorted(preview["outputs"]),
                        "external_calls": [], "snapshot_invalidated": not dry_run},
            "diff": {"output_sha256": preview["output_sha256"],
                     "readset_sha256": preview["readset_sha256"],
                     "paths": sorted(preview["outputs"])},
            "targets": [],
            "validation": {"kind": "local_proposal_only", "main_unchanged": True},
        }
    else:
        planned = _PLANNERS[spec.planner](root, config, dict(params), dry_run)
    effects = planned["effects"]
    targets = [str(target) for target in planned.get("targets", ())]
    preconditions = [
        {"id": "session", "expected": str(session.get("session_id") or "")},
        {"id": "capabilities", "expected": list(spec.capability)},
        {"id": "branch", "expected": current_branch(root)},
        {"id": "worktree_fingerprint", "expected": worktree_fingerprint(root, config)},
        {"id": "config_fingerprint", "expected": config_fingerprint(root)},
        {"id": "targets_exist", "expected": targets},
        {"id": "checkout_lock", "expected": "available"},
    ]
    if spec.planner in {"proposal_publish", "proposal_promote"}:
        code, origin = _run_git(root, ["remote", "get-url", "origin"])
        if code:
            return {"ok": False, "error_code": ERROR_PLAN_STALE, "failed_preconditions": ["origin"]}
        preconditions.append({"id": "origin_sha256", "expected": hashlib.sha256(origin.strip().encode()).hexdigest()})
        code, push = _run_git(root, ["remote", "get-url", "--push", "--all", "origin"])
        if code or push.strip() != origin.strip():
            return {"ok": False, "error_code": ERROR_INVALID_PARAMS, "detail": "effective push destination must match the reviewed repository"}
        preconditions.append({"id": "push_origin_sha256", "expected": hashlib.sha256(push.strip().encode()).hexdigest()})
    content = {
        "schema_version": ADMIN_PLAN_SCHEMA_VERSION,
        "command_id": spec.id,
        "title": spec.title,
        "params": {str(key): str(value) for key, value in params.items()},
        "dry_run": dry_run,
        "risk_level": spec.risk_level,
        "capability": list(spec.capability),
        "summary": str(planned["summary"]),
        "preconditions": preconditions,
        "effects": effects,
        "diff": planned.get("diff"),
        "validation": planned.get("validation") or {"kind": "none"},
        "undo": planned.get("undo") or _no_undo(),
        "confirmation": _confirmation_spec(spec, effects),
    }
    return {
        "ok": True,
        "plan_id": f"plan_{secrets.token_hex(8)}",
        "plan_sha": plan_sha_for(content),
        "expires_in_s": PLAN_TTL_S,
        "plan": content,
    }


# ---------------------------------------------------------------------------
# plan store (in-memory, per operator process — like admin sessions)
# ---------------------------------------------------------------------------


class AdminPlanStore:
    """Bounded in-memory store of materialized plans.

    Plans die with the process on purpose: they describe a specific reviewed
    reality, and a restarted operator has no way to prove that reality still
    holds. Each plan is single-use — executing (or failing to execute past
    the precondition gate) consumes it, and replanning is cheap.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Test seam, mirroring AdminSessionManager.clock.
        self.clock: Callable[[], float] = time.monotonic

    def _prune_locked(self, now: float) -> None:
        expired = [
            plan_id
            for plan_id, record in self._plans.items()
            if now - record["created"] > PLAN_TTL_S
        ]
        for plan_id in expired:
            del self._plans[plan_id]
        while len(self._plans) > MAX_PLANS:
            self._plans.popitem(last=False)

    def put(
        self, plan_id: str, plan_sha: str, content: dict[str, Any], session_id: str
    ) -> None:
        now = self.clock()
        with self._lock:
            self._plans[plan_id] = {
                "plan_id": plan_id,
                "plan_sha": plan_sha,
                "content": content,
                "session_id": session_id,
                "created": now,
                "status": "planned",
            }
            self._prune_locked(now)

    def peek(self, plan_id: str) -> dict[str, Any] | None:
        now = self.clock()
        with self._lock:
            self._prune_locked(now)
            record = self._plans.get(str(plan_id or ""))
            return dict(record) if record is not None else None

    def consume(self, plan_id: str) -> bool:
        """Atomically transition one plan from planned to executed.

        The status check and the transition share the store lock, so exactly
        ONE caller can ever win. Two racing execute requests that both passed
        the earlier peek-based checks (taken from a stale copy) still cannot
        both run the plan — the single-use invariant is enforced here, not by
        the advisory status check on the peeked record.
        """

        with self._lock:
            record = self._plans.get(plan_id)
            if record is None or record["status"] != "planned":
                return False
            record["status"] = "executed"
            return True

    def discard(self, plan_id: str) -> None:
        with self._lock:
            self._plans.pop(plan_id, None)


# ---------------------------------------------------------------------------
# execution bound to the reviewed plan (§9.3, §11.3)
# ---------------------------------------------------------------------------


def _redact_output(value: Any) -> Any:
    """Never-audit keys removed AND secret-shaped string values blanked."""

    value = redact_audit_value(value)

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            return redact_secret_values(item)
        if isinstance(item, dict):
            return {key: walk(entry) for key, entry in item.items()}
        if isinstance(item, list):
            return [walk(entry) for entry in item]
        return item

    return walk(value)


def _failed_preconditions(
    root: Path, config: WikiConfig, content: dict[str, Any]
) -> list[str]:
    failed: list[str] = []
    expected = {
        str(item.get("id")): item.get("expected")
        for item in content.get("preconditions", ())
    }
    if expected.get("branch") != current_branch(root):
        failed.append("branch")
    if expected.get("worktree_fingerprint") != worktree_fingerprint(root, config):
        failed.append("worktree_fingerprint")
    if expected.get("config_fingerprint") != config_fingerprint(root):
        failed.append("config_fingerprint")
    if "origin_sha256" in expected:
        code, origin = _run_git(root, ["remote", "get-url", "origin"])
        if code or hashlib.sha256(origin.strip().encode()).hexdigest() != expected["origin_sha256"]:
            failed.append("origin_sha256")
    if "push_origin_sha256" in expected:
        code, push = _run_git(root, ["remote", "get-url", "--push", "--all", "origin"])
        if code or hashlib.sha256(push.strip().encode()).hexdigest() != expected["push_origin_sha256"]:
            failed.append("push_origin_sha256")
    for target in expected.get("targets_exist") or ():
        candidate = Path(str(target))
        if candidate.is_absolute() or ".." in candidate.parts:
            failed.append("targets_exist")
            break
        if not (root / candidate).exists():
            failed.append("targets_exist")
            break
    return failed


def execute_admin_plan(
    root: Path,
    config: WikiConfig,
    store: AdminPlanStore,
    spec_lookup: Callable[[str], AdminCommandSpec | None],
    *,
    plan_id: str,
    plan_sha: str,
    confirmation: str | None,
    session: dict[str, Any],
    session_manager: AdminSessionManager,
    session_token: str,
) -> dict[str, Any]:
    """Execute one reviewed plan, revalidating EVERYTHING first (§9.3)."""

    record = store.peek(plan_id)
    if record is None:
        return {"ok": False, "error_code": ERROR_PLAN_NOT_FOUND}
    if record["session_id"] != str(session.get("session_id") or ""):
        # A different (or re-unlocked) session may not run someone else's
        # reviewed plan — replan under the current session.
        return {
            "ok": False,
            "error_code": ERROR_PLAN_STALE,
            "failed_preconditions": ["session"],
        }
    supplied_sha = str(plan_sha or "")
    if not _constant_time_eq(supplied_sha, str(record["plan_sha"])):
        return {"ok": False, "error_code": ERROR_PLAN_SHA_MISMATCH}
    if record["status"] != "planned":
        return {"ok": False, "error_code": ERROR_PLAN_ALREADY_EXECUTED}
    content = record["content"]
    spec = spec_lookup(str(content.get("command_id") or ""))
    if spec is None:  # pragma: no cover - a stored plan always has its spec
        return {"ok": False, "error_code": ERROR_UNKNOWN_COMMAND}
    granted, reason = command_capabilities_granted(config, spec, session)
    if not granted:
        # §22.5: capability revoked between plan and execute -> refusal.
        return {
            "ok": False,
            "error_code": ERROR_CAPABILITY_DENIED,
            "reason": reason,
        }
    needed = content.get("confirmation") or {"kind": "none", "text": None}
    if needed.get("kind") != "none":
        expected_text = str(needed.get("text") or "")
        if confirmation is None or confirmation == "":
            return {
                "ok": False,
                "error_code": ERROR_CONFIRMATION_REQUIRED,
                "confirmation": dict(needed),
            }
        if not _constant_time_eq(str(confirmation), expected_text):
            return {"ok": False, "error_code": ERROR_CONFIRMATION_MISMATCH}
    # One checkout, one writer (§9.3): compose with the same lock the git
    # workflows and the Codex job runner serialize on. Non-blocking — a busy
    # checkout is an honest, retryable refusal, never a queued surprise.
    if not CHECKOUT_LOCK.acquire(blocking=False):
        return {"ok": False, "error_code": ERROR_CHECKOUT_BUSY, "retryable": True}
    try:
        failed = _failed_preconditions(root, config, content)
        if failed:
            # The reviewed reality is gone; the plan can never become valid
            # again, so consume it and force a replan.
            store.discard(plan_id)
            return {
                "ok": False,
                "error_code": ERROR_PLAN_STALE,
                "failed_preconditions": failed,
            }
        if not store.consume(plan_id):
            # A concurrent execute for the same plan won the race after our
            # earlier peek: refuse instead of running the reviewed plan twice.
            return {"ok": False, "error_code": ERROR_PLAN_ALREADY_EXECUTED}
        dry_run = bool(content.get("dry_run"))
        try:
            if spec.executor == "proposal_adopt":
                from wiki_core.web.normal_proposal import adopt_proposal
                result = {"ok": True, "dry_run": True} if dry_run else adopt_proposal(
                    root, config, content["diff"], manager=session_manager, token=session_token,
                    session_id=str(record["session_id"]))
                if not result.get("ok"):
                    return {"ok": False, "error_code": _proposal_error_code(result.get("error_code", ERROR_COMMAND_FAILED)),
                            "output": _redact_output(result), "snapshot_invalidated": True}
                outcome = {"output": result, "affected_paths": [], "snapshot_invalidated": not dry_run}
            elif spec.executor == "proposal_promote":
                from wiki_core.web.normal_proposal import promote_proposal
                result = {"ok": True, "dry_run": True} if dry_run else promote_proposal(
                    root, config, content["params"], manager=session_manager,
                    token=session_token, session_id=str(record["session_id"]))
                if not result.get("ok"):
                    return {"ok": False, "error_code": _proposal_error_code(result.get("error_code", ERROR_COMMAND_FAILED)), "output": _redact_output(result)}
                outcome = {"output": result, "affected_paths": [], "snapshot_invalidated": False}
            elif spec.executor == "proposal_publish":
                from wiki_core.web.normal_proposal import publish_proposal
                params = content["params"]
                result = {"ok": True, "dry_run": True} if dry_run else publish_proposal(
                    root, config, expected_head=params["expected_head"], operation=params["operation"],
                    payload={key: params[key] for key in ("title", "body") if key in params},
                    manager=session_manager, token=session_token, session_id=str(record["session_id"]))
                if not result.get("ok"):
                    return {"ok": False, "error_code": ERROR_COMMAND_FAILED, "output": _redact_output(result)}
                outcome = {"output": result, "affected_paths": [], "snapshot_invalidated": False}
            elif spec.executor in {"openclaw_dispatch", "openclaw_inspect", "openclaw_receipt", "openclaw_resolve_failed"}:
                from wiki_core.web.openclaw import dispatch, inspect, prepare_receipt_material, resolve_failed
                def runtime_effect():
                    if dry_run:
                        return {"dry_run": True, "new_dispatch": False, "canonical_write": False}
                    if spec.executor == "openclaw_dispatch":
                        return dispatch(root, config, content["diff"])
                    if spec.executor == "openclaw_resolve_failed":
                        return resolve_failed(root, config, content["params"], content["diff"])
                    if spec.executor == "openclaw_receipt":
                        from wiki_core.coordination import digest
                        return prepare_receipt_material(root, config, content["params"],
                            expected_result_sha256=digest(content["diff"]["result"]))
                    return inspect(root, config, content["params"])
                admitted = session_manager.execute_current(
                    session_token, str(record["session_id"]), spec.capability, runtime_effect)
                if not admitted.get("ok"):
                    return admitted
                outcome = {"output": admitted["result"], "affected_paths": [], "snapshot_invalidated": False}
            elif spec.executor == "normal_proposal":
                from wiki_core.web.normal_proposal import prepare_proposal
                outcome = prepare_proposal(
                    root, config, content["params"],
                    expected_output_sha256=content["diff"]["output_sha256"],
                    expected_readset_sha256=content["diff"]["readset_sha256"],
                    manager=session_manager, token=session_token,
                    session_id=str(record["session_id"]), dry_run=dry_run,
                )
                if outcome.get("failed"):
                    return {"ok": False, "error_code": _proposal_error_code(outcome["output"]["error_code"]),
                            "status": "partial" if outcome["affected_paths"] else "refused",
                            "output": _redact_output(outcome["output"]),
                            "affected_paths": outcome["affected_paths"],
                            "snapshot_invalidated": bool(outcome["affected_paths"])}
            else:
                admitted = session_manager.execute_current(
                    session_token, str(record["session_id"]), spec.capability,
                    lambda: _EXECUTORS[spec.executor](root, config, dry_run),
                )
                if not admitted.get("ok"):
                    return admitted
                outcome = admitted["result"]
        except Exception as exc:  # noqa: BLE001 - executor boundary fails closed
            return {
                "ok": False,
                "error_code": _proposal_error_code(getattr(exc, "code", ERROR_COMMAND_FAILED)),
                "failed_preconditions": [getattr(exc, "code", ERROR_COMMAND_FAILED)],
                "plan_id": plan_id,
                "plan_sha": record["plan_sha"],
                "command_id": spec.id,
                "status": "failed",
                "output": {"error": redact_secret_values(str(exc))},
            }
    finally:
        CHECKOUT_LOCK.release()
    return {
        "ok": True,
        "plan_id": plan_id,
        "plan_sha": record["plan_sha"],
        "command_id": spec.id,
        "risk_level": spec.risk_level,
        "dry_run": dry_run,
        "status": "success",
        "output": _redact_output(outcome.get("output")),
        "affected_paths": list(outcome.get("affected_paths") or ()),
        "branch": current_branch(root) or None,
        "snapshot_invalidated": bool(outcome.get("snapshot_invalidated")),
        "undo": outcome.get("undo") or content.get("undo") or _no_undo(),
    }
