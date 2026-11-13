"""Provider-neutral action-body proposals over Git and the canonical writer.

No worker, task database, authority grant or transcript store. Callers are
trusted local operators. GitHub is used only when the consumer selects its PR
policy; material/review input is never interpreted as human or CI approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from contextlib import ExitStack

from wiki_core.action_transition import (
    ActionTransitionError, _action_file_lock, _assert_no_secrets,
    _contained_action_path, _parse_document, integrate_action_body,
    action_transition_diagnostics, _SUPPORT_FIELDS, contribution_log_text, append_contribution_log,
)
from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths

SCHEMA = "wiki_action_contribution.v1"
COVERAGE = "one_action_body_and_existing_memory_log_annotation"
C3_COVERAGE = "one_action_body_existing_memory_log_and_declared_freshness_contract"
OPERATIONS = frozenset({"prepare_contribution", "publish_contribution", "integrate_contribution", "reconcile_contribution"})


class ContributionError(ValueError):
    """Safe refusal with bounded, redacted gate diagnostics when available."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _run(root: Path, *argv: str, timeout: int = 120) -> str:
    try:
        p = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContributionError("command_outcome_unknown: reconcile before retry") from exc
    if p.returncode:
        if argv[:3] in {("gh", "pr", "merge"), ("gh", "pr", "create")}:
            raise ContributionError("command_outcome_unknown: reconcile before retry")
        raise ContributionError("command_failed:" + argv[0])
    return p.stdout.strip()


def _git(root: Path, *argv: str) -> str:
    return _run(root, "git", *argv)


def _blob(root: Path, revision: str, path: str) -> str:
    # Do not strip terminal newlines: these hashes bind the actual bytes.
    p = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=root, capture_output=True)
    if p.returncode:
        raise ContributionError("source_blob_unavailable")
    return p.stdout.decode("utf-8")


def _string(value: Any, label: str, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ContributionError("invalid_" + label)
    return value


def _request(config: WikiConfig, request: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(request, dict) or request.get("schema_version") != SCHEMA:
        raise ContributionError("unsupported_contribution")
    task = request.get("task_ref")
    if not isinstance(task, dict) or task.get("repo_id") != config.repo_id:
        raise ContributionError("task_repo_mismatch")
    _string(task.get("action_id"), "action_id")
    run, session = request.get("run_ref"), request.get("session_ref")
    if not isinstance(run, dict) or not isinstance(session, dict):
        raise ContributionError("missing_run_or_session_ref")
    for field in ("runtime", "task_id", "run_id"):
        _string(run.get(field), field)
    _string(session.get("session_id"), "session_id")
    _string(session.get("coverage"), "history_coverage", 2000)
    files = request.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ContributionError("one_existing_action_only")
    item = files[0]
    path = _string(item.get("path"), "path")
    text = _string(item.get("text"), "text", 500_000)
    if item.get("sha256") != _sha(text):
        raise ContributionError("material_file_hash_mismatch")
    key = _string(request.get("effect_key"), "effect_key", 200)
    material = digest({k: v for k, v in request.items() if k != "material_sha256"})
    if request.get("material_sha256", material) != material:
        raise ContributionError("material_hash_mismatch")
    _assert_no_secrets(json.dumps(request, ensure_ascii=False))
    from wiki_core.web.git_workflows import _proposal_branch
    branch = _proposal_branch(config, "contribution-" + digest({"task": task, "effect_key": key})[:32])
    if branch is None:
        raise ContributionError("invalid_proposal_prefix")
    return path, material, branch


def _review(request: dict[str, Any], material: str, review: Any) -> dict[str, Any]:
    if not isinstance(review, dict) or review.get("material_sha256") != material:
        raise ContributionError("exact_material_review_required")
    reviewer = _string(review.get("reviewer_session_id"), "reviewer_session_id")
    if reviewer == request["session_ref"]["session_id"]:
        raise ContributionError("independent_reviewer_required")
    _string(review.get("evidence_ref"), "review_evidence_ref")
    report = review.get("report")
    def valid_criterion(item: Any) -> bool:
        if isinstance(item, str):
            return bool(item.strip())
        return (isinstance(item, dict) and isinstance(item.get("criterion"), str)
                and bool(item["criterion"].strip()) and item.get("met") is True
                and isinstance(item.get("evidence_refs"), list) and bool(item["evidence_refs"])
                and all(isinstance(ref, str) and ref.strip() for ref in item["evidence_refs"]))
    if (review.get("decision") != "approved" or not isinstance(report, dict)
        or not isinstance(report.get("criteria"), list) or not report["criteria"]
        or not all(valid_criterion(c) for c in report["criteria"])
        or not isinstance(report.get("findings"), list)
        or any(not isinstance(f, dict) or f.get("blocking") is not False for f in report["findings"])):
        raise ContributionError("review_not_approved")
    digest(review)  # reject non-finite JSON; preserve the original report losslessly
    _assert_no_secrets(json.dumps(review, ensure_ascii=False))
    return review


def _head_review(request: dict, material: str, commit: str, review: Any,
                 *, candidate_files: list[dict] | None = None) -> dict:
    if not isinstance(review, dict) or review.get("proposal_commit") != commit:
        raise ContributionError("exact_generated_head_review_required")
    review = _review(request, material, review)
    if candidate_files is not None and review.get("candidate_files") != candidate_files:
        raise ContributionError("exact_candidate_files_review_required")
    return review


def _local_ref(value: Any) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
        or Path(value).is_absolute() or Path(value).as_posix() != value
        or any(p in {".", "..", ".git"} for p in Path(value).parts)):
        raise ContributionError("invalid_contribution_c3_path")
    return value


def _local_file(root: Path, path: str, expected: str | None = None, *, mode: str | None = None) -> str:
    current = root.resolve()
    for part in Path(_local_ref(path)).parts:
        current /= part
        if current.is_symlink():
            raise ContributionError("contribution_symlink_path")
    if not current.is_file() or not current.resolve().is_relative_to(root.resolve()):
        raise ContributionError("contribution_file_unavailable")
    actual_mode = "100755" if current.stat().st_mode & 0o111 else "100644"
    payload = current.read_bytes()
    if (expected is not None and payload != expected.encode()) or (mode is not None and actual_mode != mode):
        raise ContributionError("contribution_local_file_changed:" + path)
    return payload.decode("utf-8")


def _mode(root: Path, revision: str, path: str) -> str:
    return _git(root, "ls-tree", "--format=%(objectmode)", revision, "--", path)


def _tracked_regular(root: Path, revision: str, path: str, *, executable: bool | None = None) -> str:
    mode = _mode(root, revision, path)
    if mode not in {"100644", "100755"} or (executable is not None and (mode == "100755") != executable):
        raise ContributionError("contribution_c3_requires_tracked_regular_file")
    return _blob(root, revision, path)


def _c3_policy(root: Path, revision: str) -> dict | None:
    """Read only committed consumer policy/code; no command comes from input."""
    import yaml
    policy = yaml.safe_load(_blob(root, revision, "wiki.config.yaml")) or {}
    value = (policy.get("approval") or {}).get("contribution_c3")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"argv", "derived_paths"}:
        raise ContributionError("invalid_contribution_c3_policy")
    argv = value.get("argv")
    if (not isinstance(argv, list) or not argv or len(argv) > 32
        or any(not isinstance(v, str) or not v or len(v) > 2000 or "\x00" in v for v in argv)
        or any(v == "--contribution-file" or v.startswith("--contribution-file=") for v in argv)):
        raise ContributionError("invalid_contribution_c3_argv")
    _assert_no_secrets(json.dumps(argv, ensure_ascii=False))
    # A direct executable owned by the repository, or an explicit interpreter
    # and tracked script. Inline code, shells and ambient plugin commands have
    # no qualified source here. This is provenance, not a process sandbox.
    # Only fixed interpreter names, resolved by the same trusted operator
    # environment as normal gates. A repo-relative interpreter is not trusted.
    interpreter = bool(re.fullmatch(r"python(?:[0-9.]+)?|node", argv[0]))
    if interpreter:
        if len(argv) < 2:
            raise ContributionError("contribution_c3_source_required")
        source = _local_ref(argv[1])
    else:
        source = _local_ref(argv[0])
    code = _tracked_regular(root, revision, source, executable=None if interpreter else True)
    metadata = _local_ref((policy.get("audit") or {}).get("freshness_records"))
    memory_root = str((policy.get("paths") or {}).get("memory_root") or "memories")
    if (value["derived_paths"] != [metadata] or Path(metadata).suffix != ".json"
        or Path(metadata).is_relative_to(Path(memory_root)) or source == metadata):
        raise ContributionError("contribution_c3_only_existing_freshness_contract")
    _metadata_update(_tracked_regular(root, revision, metadata, executable=False), None)
    return {"argv": list(argv), "derived_paths": [metadata], "source_ref": source,
            "source_sha256": _sha(code), "interpreter": interpreter}


def _authored_preparation(request: dict, c3: dict | None) -> None:
    value = request.get("consumer_preparation")
    if c3 is None:
        if value is not None:
            raise ContributionError("consumer_preparation_without_committed_policy")
        return
    if (not isinstance(value, dict) or set(value) != {"schema_version", "authored_plan"}
        or value.get("schema_version") != "wiki_consumer_preparation.v1"
        or not isinstance(value.get("authored_plan"), dict) or not value["authored_plan"]):
        raise ContributionError("reviewed_consumer_preparation_plan_required")
    # This is transport of reviewed authorship, NOT validation of its meaning.
    # The committed consumer script must validate its own semantic plan, and
    # the independent head reviewer must review the resulting complete delta.


def _local_validation(config: WikiConfig) -> bool:
    value = config.approval.get("contribution_validation")
    if value is None:
        return False
    if value != {"mode": "local"} or not isinstance(config.approval.get("contribution_gates"), list) or not config.approval["contribution_gates"]:
        raise ContributionError("invalid_contribution_validation_policy")
    return True


def _metadata_update(before: str, after: str | None, *, request: dict | None = None,
                     action_ref: str | None = None, entry: dict | None = None) -> None:
    old = json.loads(before)
    if not isinstance(old, dict) or old.get("schema_version") != "document_record.v1":
        raise ContributionError("contribution_c3_requires_document_record_contract")
    if after is None:
        return
    new = json.loads(after)
    planned_artifacts = ((request or {}).get("consumer_preparation") or {}).get("authored_plan", {}).get("added_artifacts", [])
    if not isinstance(planned_artifacts, list):
        raise ContributionError("invalid_authored_artifact_plan")
    added = []
    for artifact in planned_artifacts:
        if (not isinstance(artifact, dict) or set(artifact) != {"origin", "id", "document", "field", "match_key", "match_value", "sha256"}
            or artifact.get("origin") != "current" or artifact.get("document") != action_ref
            or artifact.get("field") != "action_state_history" or artifact.get("match_key") != "receipt_id"
            or artifact.get("match_value") != "$receipt_id" or artifact.get("sha256") != "$receipt_sha256"
            or not entry):
            raise ContributionError("artifact_addition_requires_authored_generated_receipt_selector")
        from wiki_core.document_records import structured_digest
        added.append({**artifact, "match_value": entry["receipt_id"], "sha256": structured_digest(entry)})
    mutable = {"current_documents_sha256", "documents", "bindings", "artifacts"}
    expected_keys = set(old) | ({"artifacts"} if added else set())
    if (not isinstance(new, dict) or set(new) != expected_keys
        or any(new[k] != v for k, v in old.items() if k not in mutable)):
        raise ContributionError("contribution_c3_changed_frozen_evidence_or_base")
    if new.get("artifacts", []) != [*old.get("artifacts", []), *added]:
        raise ContributionError("contribution_c3_changed_frozen_artifacts")
    # Prior authored historical assertions are not recaptured or relabelled.
    # New assertions/bindings still need the consumer's semantic validation and
    # independent review; current hashes alone never establish independence.
    for document in old.get("documents", []):
        matches = [d for d in new.get("documents", []) if d.get("path") == document.get("path")]
        if len(matches) != 1:
            raise ContributionError("contribution_c3_changed_historical_records")
        for record in document.get("records", []):
            records = [r for r in matches[0].get("records", []) if r.get("id") == record.get("id")]
            if len(records) != 1 or any(records[0].get(k) != v for k, v in record.items() if k != "current_sha256"):
                raise ContributionError("contribution_c3_changed_historical_records")
    if any(b not in new.get("bindings", []) for b in old.get("bindings", []) if b.get("origin") == "base"):
        raise ContributionError("contribution_c3_changed_historical_bindings")
    _assert_no_secrets(json.dumps(new, ensure_ascii=False, allow_nan=False))


def _candidate_files(root: Path, parent: str, commit: str) -> list[dict]:
    return [{"path": p, "sha256": _sha(_blob(root, commit, p))}
            for p in _git(root, "diff", "--name-only", parent, commit).splitlines()]


def _proposal_manifest(root: Path, commit: str) -> dict:
    parent = _git(root, "rev-parse", commit + "^")
    return {"proposal_commit": commit, "proposal_tree": _git(root, "rev-parse", commit + "^{tree}"),
            "candidate_files": _candidate_files(root, parent, commit)}


def _protected_inputs(root: Path, parent: str, c3: dict | None) -> dict[str, tuple[str, str]]:
    paths = ["wiki.config.yaml", *([c3["source_ref"], *c3["derived_paths"]] if c3 else [])]
    return {p: (_tracked_regular(root, parent, p), _mode(root, parent, p)) for p in paths}


def _run_c3(scratch: Path, c3: dict, request: dict, receipt: dict, log_ref: str,
            log_heading: str, input_path: Path) -> dict:
    descriptor = os.open(input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"request": request, "action_receipt": receipt,
                   "generated_log": {"path": log_ref, "heading": log_heading},
                   "derived_paths": c3["derived_paths"]}, stream, ensure_ascii=False, allow_nan=False)
    argv = list(c3["argv"])
    if c3["interpreter"]:
        executable = shutil.which(argv[0])
        if not executable or Path(executable).resolve().is_relative_to(scratch.resolve()):
            raise ContributionError("consumer_c3_interpreter_unavailable")
        argv[0] = executable
    else:
        argv[0] = str(scratch / argv[0])
    executable_sha = hashlib.sha256(Path(argv[0]).read_bytes()).hexdigest()
    try:
        done = subprocess.run([*argv, "--contribution-file", str(input_path)], cwd=scratch,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContributionError("consumer_c3_failed", {"c3_outcome": "unknown"}) from exc
    evidence = {"source_ref": c3["source_ref"], "source_sha256": c3["source_sha256"],
                "executable_sha256": executable_sha,
                "exit_code": done.returncode, "output_sha256": hashlib.sha256(done.stdout + done.stderr).hexdigest()}
    if hashlib.sha256(Path(argv[0]).read_bytes()).hexdigest() != executable_sha:
        raise ContributionError("consumer_c3_interpreter_changed")
    if done.returncode:
        raise ContributionError("consumer_c3_failed", {"c3_receipt": evidence})
    return evidence


def _entry(root: Path, commit: str, path: str, request: dict, material: str,
           *, approved: str | None = None) -> tuple[dict, str]:
    parent = _git(root, "rev-parse", commit + "^")
    branch = str(load_config(root).approval.get("default_branch") or "main")
    approved = approved or _candidate_ref(root, f"refs/remotes/origin/{branch}") or _candidate_ref(root, f"refs/heads/{branch}")
    if not approved:
        raise ContributionError("approved_base_unavailable")
    _git(root, "merge-base", "--is-ancestor", parent, approved)
    log_ref = WikiPaths(root, load_config(root)).log_page.relative_to(root).as_posix()
    c3 = _c3_policy(root, parent)
    _authored_preparation(request, c3)
    allowed_paths = [path, log_ref, *(c3["derived_paths"] if c3 else [])]
    if _git(root, "diff", "--name-only", parent, commit).splitlines() != sorted(allowed_paths):
        raise ContributionError("proposal_exceeds_body_and_log_annotation")
    # Content hashes alone do not guard a 100644 -> executable/symlink change.
    for p in allowed_paths:
        _tracked_regular(root, commit, p)
        if _mode(root, parent, p) != _mode(root, commit, p):
            raise ContributionError("candidate_file_mode_changed")
    text = _blob(root, commit, path)
    fm, _ = _parse_document(text)
    history = fm.get("action_state_history") or []
    if not isinstance(history, list) or any(not isinstance(e, dict) for e in history):
        raise ContributionError("invalid_action_history")
    found = [e for e in history if e.get("kind") == "body_integration"
             and isinstance(e.get("contribution"), dict)
             and e["contribution"].get("effect_key") == request["effect_key"]]
    if len(found) != 1 or fm.get("page_id") != request["task_ref"]["action_id"]:
        raise ContributionError("contribution_receipt_missing")
    entry = found[0]
    metadata = entry["contribution"]
    if c3:
        for p in c3["derived_paths"]:
            _metadata_update(_blob(root, parent, p), _blob(root, commit, p),
                             request=request, action_ref=path, entry=entry)
    if metadata.get("log_format") != ("record_v1" if c3 else None):
        raise ContributionError("candidate_log_format_tampered")
    if metadata.get("material_sha256") != material:
        raise ContributionError("effect_key_conflict")
    known = _known_base(root, path, request["files"][0])
    known_fm, _ = _parse_document(known)
    proposed_fm, proposed_body = _parse_document(request["files"][0]["text"])
    parent_text = _blob(root, parent, path)
    parent_fm, _ = _parse_document(parent_text)
    _, actual_body = _parse_document(text)
    allowed = {*_SUPPORT_FIELDS, "action_state", "action_state_history", "updated_at", "completed_at"}
    if (known_fm != proposed_fm or proposed_body != actual_body or history[-1] != entry
        or {k: v for k, v in fm.items() if k not in allowed} !=
           {k: v for k, v in parent_fm.items() if k not in allowed}
        or action_transition_diagnostics(parent_text, text)):
        raise ContributionError("candidate_material_or_frontmatter_tampered")
    for field in ("task_ref", "run_ref", "session_ref"):
        if metadata.get(field) != request[field]:
            raise ContributionError("candidate_reference_tampered")
    _review(request, material, metadata.get("review"))
    expected_log = contribution_log_text(_blob(root, parent, log_ref), path, log_ref, material, entry["at"],
                                         log_format=metadata.get("log_format"))
    if _blob(root, commit, log_ref) != expected_log:
        raise ContributionError("candidate_log_annotation_tampered")
    return entry, text


def _gates(root: Path, config: WikiConfig, *, frozen_commit: str | None = None) -> list[dict]:
    from wiki_core.web.gates import GATE_COMMANDS
    catalog = dict(GATE_COMMANDS)
    commands = [
        [sys.executable, *catalog["wiki_audit"][1:]],
        [sys.executable, *catalog["input_stage"][1:]],
        [sys.executable, "scripts/wiki_pr_summary.py"],
        ["git", "diff", "--check"],
    ]
    extra = config.approval.get("contribution_gates", [])
    if not isinstance(extra, list) or any(not isinstance(c, list) or not c or
            any(not isinstance(x, str) or not x for x in c) for c in extra):
        raise ContributionError("invalid_policy_gates")
    results = []
    baseline = _gate_input_state(root)
    for command in [*commands, *extra]:
        if frozen_commit:
            _immutable_candidate(root, frozen_commit)
        # Resolve explicit relative programs at the candidate, never at the
        # application's process cwd. Bare names retain the normal gate PATH.
        executable = (str(root / command[0]) if "/" in command[0] and not Path(command[0]).is_absolute()
                      else shutil.which(command[0]))
        if not executable:
            raise ContributionError("gate_unavailable")
        executable = str(Path(executable).resolve())
        executable_sha = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        try:
            p = subprocess.run([executable, *command[1:]], cwd=root, capture_output=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContributionError("gate_unavailable") from exc
        results.append({"argv": command, "exit_code": p.returncode,
                        "executable_sha256": executable_sha,
                        "output_sha256": hashlib.sha256(p.stdout + p.stderr).hexdigest()})
        if hashlib.sha256(Path(executable).read_bytes()).hexdigest() != executable_sha:
            raise ContributionError("gate_executable_changed", {"gate_receipts": results})
        if _gate_input_state(root) != baseline:
            raise ContributionError("gate_modified_candidate_inputs", {"gate_receipts": results})
        if frozen_commit:
            _immutable_candidate(root, frozen_commit)
        if p.returncode:
            from wiki_core.web.commands import SECRET_VALUE_RE
            output = (p.stdout + p.stderr).decode("utf-8", errors="replace")
            try:
                _assert_no_secrets(output)
            except ActionTransitionError:
                output = "Gate output contains an access-secret finding; content omitted."
            results[-1]["diagnostic_tail"] = SECRET_VALUE_RE.sub(
                lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", output[-4000:])
            results[-1]["diagnostic_truncated"] = len(output) > 4000
            raise ContributionError("proposal_gate_failed:" + Path(command[0]).name,
                                    {"gate_receipts": results})
    return results


def _gate_input_state(root: Path) -> tuple[str, str, str]:
    # Includes index, modes, HEAD and all nonignored untracked paths. Ignored
    # caches are not source; existing generators may create them normally.
    return (_git(root, "rev-parse", "HEAD"),
            _git(root, "status", "--porcelain", "--untracked-files=all"),
            _sha(_git(root, "diff", "--binary", "HEAD")))


def _immutable_candidate(root: Path, commit: str) -> None:
    if (_git(root, "rev-parse", "HEAD") != commit
        or _git(root, "status", "--porcelain", "--untracked-files=all")
        or _git(root, "rev-parse", "HEAD^{tree}") != _git(root, "rev-parse", commit + "^{tree}")):
        raise ContributionError("gate_modified_immutable_candidate")


def _validate_local_candidate(root: Path, commit: str) -> dict:
    """Use the existing gate operation on exact Git content, not old receipts.

    This is trusted committed consumer code, not a process/network sandbox.
    No C3, model, proposal write or external promotion is invoked here.
    """
    with tempfile.TemporaryDirectory(prefix="wiki-contribution-validation-") as temporary:
        scratch = Path(temporary) / "candidate"
        _run(root, "git", "clone", "--shared", "--no-checkout", str(root), str(scratch))
        _git(scratch, "checkout", "--detach", commit)
        _immutable_candidate(scratch, commit)
        config = load_config(scratch)
        if not _local_validation(config):
            raise ContributionError("local_validation_not_declared")
        gates = _gates(scratch, config, frozen_commit=commit)
        _immutable_candidate(scratch, commit)
        sources = []
        for path in sorted({arg for g in gates for arg in g["argv"]
                            if not arg.startswith("-") and not Path(arg).is_absolute()}):
            mode = _mode(scratch, commit, path)
            if mode in {"100644", "100755"}:
                sources.append({"path": path, "sha256": _sha(_blob(scratch, commit, path)), "mode": mode})
        return {"mode": "local", **_proposal_manifest(scratch, commit),
                "policy_sha256": _sha(_blob(scratch, commit, "wiki.config.yaml")),
                "command_sources": sources, "gate_receipts": gates}


def _candidate(root: Path, branch: str) -> str | None:
    return _candidate_ref(root, f"refs/heads/{branch}")


def _candidate_ref(root: Path, ref: str) -> str | None:
    p = subprocess.run(["git", "rev-parse", "--verify", ref],
                       cwd=root, text=True, capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else None


def _known_base(root: Path, path: str, item: dict) -> str:
    revision = item.get("base_commit")
    if revision:
        import re
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ContributionError("invalid_base_commit")
        _git(root, "merge-base", "--is-ancestor", revision, "HEAD")
        text = _blob(root, revision, path)
        if _sha(text) != item.get("base_sha256"):
            raise ContributionError("base_revision_hash_mismatch")
        return text
    # Compatibility for adapters that pin only the exact file hash. Search a
    # bounded ancestry, never accept a caller-authored base document as truth.
    for revision in _git(root, "log", "-200", "--format=%H", "--", path).splitlines():
        text = _blob(root, revision, path)
        if _sha(text) == item.get("base_sha256"):
            return text
    raise ContributionError("known_base_required: supply base_commit")


def _reconcile_source(known: str, current: str, proposed: str) -> str:
    old_fm, old_body = _parse_document(known)
    fm, body = _parse_document(current)
    proposed_fm, new_body = _parse_document(proposed)
    if old_fm != proposed_fm:
        raise ContributionError("frontmatter_changes_not_supported")
    if old_body != body:
        raise ContributionError("source_body_conflict")
    if current != known:
        # Permit only legitimate canonical transition suffixes, not arbitrary
        # history exclusions or owner/tool/authority changes.
        allowed = {*_SUPPORT_FIELDS, "action_state", "action_state_history", "updated_at", "completed_at"}
        if ({k: v for k, v in fm.items() if k not in allowed} !=
            {k: v for k, v in old_fm.items() if k not in allowed}):
            raise ContributionError("source_authority_or_frontmatter_conflict")
        history = fm.get("action_state_history") or []
        prior = old_fm.get("action_state_history") or []
        if len(history) <= len(prior) or action_transition_diagnostics(known, current):
            raise ContributionError("unproved_source_history_suffix")
    return new_body


def _prepare(root: Path, config: WikiConfig, request: dict, review: dict | None,
             *, dry_run: bool = False) -> dict:
    path, material, branch = _request(config, request)
    review = _review(request, material, review)
    existing = _candidate(root, branch)
    if existing:
        entry, text = _entry(root, existing, path, request, material)
        if entry["contribution"]["review"] != review:
            raise ContributionError("effect_review_conflict")
        c3 = _c3_policy(root, _git(root, "rev-parse", existing + "^"))
        return {"status": "prepared", **_proposal_manifest(root, existing), "branch": branch,
                "material_sha256": material, "receipt_id": entry["receipt_id"],
                "after_sha256": _sha(text), "idempotent": True, "coverage": C3_COVERAGE if c3 else COVERAGE}
    target, path = _contained_action_path(root, path)
    base = _git(root, "rev-parse", "HEAD")
    approved_branch = str(config.approval.get("default_branch") or "main")
    refs = [f"refs/remotes/origin/{approved_branch}", f"refs/heads/{approved_branch}"]
    approved = None
    for ref in refs:
        try:
            approved = _git(root, "rev-parse", "--verify", ref)
            break
        except ContributionError:
            continue
    if approved != base:
        raise ContributionError("checkout_not_at_approved_base")
    before = target.read_text()
    item = request["files"][0]
    known = _known_base(root, path, item)
    committed = _blob(root, base, path)
    # Validate both committed evolution and any local canonical dialogue
    # suffix. Both chains must be real; current WIP is never silently dropped.
    _reconcile_source(known, committed, item["text"])
    body = _reconcile_source(known, before, item["text"])
    fm, _ = _parse_document(before)
    if fm.get("page_id") != request["task_ref"]["action_id"]:
        raise ContributionError("task_action_mismatch")
    source_log_ref = WikiPaths(root, config).log_page.relative_to(root).as_posix()
    source_log_path, _ = _contained_action_path(root, source_log_ref)
    source_log = source_log_path.read_text()
    if source_log != _blob(root, base, source_log_ref):
        raise ContributionError("log_overlap_reconcile_required")
    policy = _blob(root, base, "wiki.config.yaml")
    if (root / "wiki.config.yaml").read_text() != policy:
        raise ContributionError("uncommitted_policy")
    c3 = _c3_policy(root, base)
    _authored_preparation(request, c3)
    _local_validation(config)
    protected = _protected_inputs(root, base, c3)
    for p, (text, mode) in protected.items():
        _local_file(root, p, text, mode=mode)
    coverage = C3_COVERAGE if c3 else COVERAGE
    if dry_run:
        return {"status": "ready_to_prepare", "material_sha256": material,
                "branch": branch, "coverage": coverage}
    # The proposal contains one body plus its required existing-log annotation. Disjoint
    # staged/unstaged/untracked files in the application's checkout stay there.
    with tempfile.TemporaryDirectory(prefix="wiki-contribution-") as temporary:
        scratch = Path(temporary) / "proposal"
        _run(root, "git", "clone", "--shared", "--no-checkout", str(root), str(scratch))
        _git(scratch, "checkout", "--detach", base)
        for field in ("user.name", "user.email"):
            _git(scratch, "config", field, _git(root, "config", field))
        # Carry only the proven current action suffix into the isolated
        # checkout, through the same canonical file boundary.
        from wiki_core.action_transition import seed_action_proposal
        seed_action_proposal(scratch, path, committed, before)
        receipt = integrate_action_body(scratch, path, body, expected_sha256=_sha(before),
            contribution={"material_sha256": material, "effect_key": request["effect_key"],
                          "task_ref": request["task_ref"], "run_ref": request["run_ref"],
                          "session_ref": request["session_ref"], "review": review,
                          **({"log_format": "record_v1"} if c3 else {})})
        log_ref = WikiPaths(scratch, load_config(scratch)).log_page.relative_to(scratch).as_posix()
        fm_after, _ = _parse_document((scratch / path).read_text())
        at = fm_after["action_state_history"][-1]["at"]
        append_contribution_log(scratch, log_ref, path, material, at,
                                log_format="record_v1" if c3 else None)
        expected_log = (scratch / log_ref).read_text()
        expected_action = (scratch / path).read_text()
        allowed_paths = [path, log_ref, *(c3["derived_paths"] if c3 else [])]
        c3_receipt = None
        if c3:
            c3_receipt = _run_c3(scratch, c3, request, receipt, log_ref,
                "[" + at[:10] + "] Reviewed action body " + material,
                Path(temporary) / "consumer-preparation.json")
            _local_file(scratch, path, expected_action, mode=_mode(root, base, path))
            _local_file(scratch, log_ref, expected_log, mode=_mode(root, base, log_ref))
            for p in c3["derived_paths"]:
                metadata_text = _local_file(scratch, p, mode="100644")
                _metadata_update(protected[p][0], metadata_text, request=request,
                                 action_ref=path, entry=fm_after["action_state_history"][-1])
            if (_git(scratch, "diff", "--name-only", base).splitlines() != sorted(allowed_paths)
                or _git(scratch, "ls-files", "--others", "--exclude-standard")
                or _git(scratch, "rev-parse", "HEAD") != base):
                raise ContributionError("consumer_c3_modified_other_paths")
        expected_files = {p: ((scratch / p).read_text(), _mode(root, base, p)) for p in allowed_paths}
        gates = _gates(scratch, load_config(scratch))
        if (scratch / log_ref).read_text() != expected_log:
            raise ContributionError("gate_modified_log_annotation")
        # Check commands may not silently modify the reviewed proposal.
        after = (scratch / path).read_text()
        if _sha(after) != receipt["after_sha256"]:
            raise ContributionError("gate_modified_proposal")
        changed = _git(scratch, "diff", "--name-only", base).splitlines()
        if changed != sorted(allowed_paths) or _git(scratch, "ls-files", "--others", "--exclude-standard"):
            raise ContributionError("gate_modified_other_paths")
        for p, (text, mode) in expected_files.items():
            _local_file(scratch, p, text, mode=mode)
        if _git(scratch, "rev-parse", "HEAD") != base:
            raise ContributionError("gate_modified_proposal_head")
        _git(scratch, "add", "--", *allowed_paths)
        _git(scratch, "commit", "-m", "wiki: integrate reviewed action body " + material[:12])
        commit = _git(scratch, "rev-parse", "HEAD")
        _entry(scratch, commit, path, request, material, approved=base)
        _immutable_candidate(scratch, commit)
        # No model/audit work under these process-shared guards. Revalidate
        # HEAD, bytes and policy immediately before installing the proposal ref.
        with (_action_file_lock(root, "contribution-ref:" + branch),
              _action_file_lock(root, path), _action_file_lock(root, source_log_ref), ExitStack() as guards):
            for p in sorted(protected):
                guards.enter_context(_action_file_lock(root, p))
            if (_git(root, "rev-parse", "HEAD") != base or target.read_text() != before
                or (root / "wiki.config.yaml").read_text() != policy
                or source_log_path.read_text() != source_log):
                raise ContributionError("source_changed_during_prepare")
            for p, (text, mode) in protected.items():
                _local_file(root, p, text, mode=mode)
            if _candidate(root, branch):
                raise ContributionError("contribution_prepared_concurrently: reconcile")
            _git(root, "fetch", "--no-write-fetch-head", str(scratch), commit)
            _git(root, "update-ref", f"refs/heads/{branch}", commit, "0" * 40)
    return {"status": "prepared", **_proposal_manifest(root, commit), "branch": branch,
            "material_sha256": material, "after_sha256": receipt["after_sha256"],
            "receipt_id": receipt["receipt_id"], "gate_receipts": gates,
            "idempotent": False, "coverage": coverage,
            "generated_paths": [log_ref, *(c3["derived_paths"] if c3 else [])],
            **({"c3_receipt": c3_receipt} if c3_receipt is not None else {})}


def _repository(root: Path) -> str:
    import re
    from urllib.parse import urlparse
    remote = _git(root, "remote", "get-url", "origin")
    if remote.startswith("git@"):
        host, separator, path = remote[4:].partition(":")
        if not separator:
            raise ContributionError("unsupported_github_remote")
    else:
        parsed = urlparse(remote)
        if parsed.scheme not in {"https", "ssh"} or parsed.password or parsed.query or parsed.fragment:
            raise ContributionError("unsupported_github_remote")
        host, path = parsed.hostname or "", parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise ContributionError("unsupported_github_remote")
    return host + "/" + path


def _gh(root: Path, *args: str) -> Any:
    return json.loads(_run(root, "gh", *args))


def _pr(root: Path, number: Any, repository: str | None = None) -> dict:
    if not str(number).isdigit():
        raise ContributionError("invalid_pr")
    return _gh(root, "pr", "view", str(number), "--repo", repository or _repository(root), "--json",
               "number,url,state,headRefOid,headRefName,headRepository,headRepositoryOwner,isCrossRepository,baseRefName,mergeCommit,statusCheckRollup,reviews,reviewDecision,isDraft")


def _fetch_canonical(root: Path, branch: str) -> str:
    return _fetch_remote_ref(root, f"refs/heads/{branch}")


def _canonical_observation(root: Path, branch: str, *, dry_run: bool = False) -> str:
    if not dry_run:
        return _fetch_canonical(root, branch)
    oid = _remote_branch(root, branch)
    if not oid or _candidate_ref(root, oid + "^{commit}") != oid:
        raise ContributionError("canonical_object_not_retained_for_dry_run_unknown")
    return oid


def _fetch_remote_ref(root: Path, source_ref: str, expected: str | None = None) -> str:
    # FETCH_HEAD is shared by unrelated fetches in this repository. Give this
    # read its own ref so local proposal/object imports cannot change identity
    # between fetch and readback; remove only our exact temporary ref.
    import uuid
    ref = "refs/wiki/contribution-read/" + uuid.uuid4().hex
    commit = None
    try:
        _git(root, "fetch", "--no-write-fetch-head", "origin", "--no-tags", "--no-prune",
             "--refmap=", "--no-auto-maintenance", f"{source_ref}:{ref}")
        commit = _git(root, "rev-parse", ref + "^{commit}")
        if expected is not None and commit != expected:
            raise ContributionError("discovered_ref_identity_changed")
        return commit
    finally:
        # A failed command may already have created its temporary ref.
        retained = _candidate_ref(root, ref)
        if retained is not None:
            _git(root, "update-ref", "-d", ref, retained)


def _remote_branch(root: Path, branch: str) -> str | None:
    p = subprocess.run(["git", "ls-remote", "--exit-code", "--refs", "origin", f"refs/heads/{branch}"],
                       cwd=root, text=True, capture_output=True, timeout=120)
    if p.returncode == 2:
        return None  # successful lookup, no such ref; not a transport failure
    if p.returncode:
        raise ContributionError("remote_ref_observation_unknown")
    rows = [line.split() for line in p.stdout.splitlines()]
    import re
    if (len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch}"
        or not re.fullmatch(r"[0-9a-f]{40}", rows[0][0])):
        raise ContributionError("remote_ref_observation_unknown")
    return rows[0][0]


def _merge_oid(pr: dict) -> str | None:
    import re
    merge = pr.get("mergeCommit")
    oid = merge.get("oid") if isinstance(merge, dict) else None
    return oid if isinstance(oid, str) and re.fullmatch(r"[0-9a-f]{40}", oid) else None


def _reconcile(root: Path, config: WikiConfig, request: dict, path: str,
               material: str, branch: str, number: Any, result: dict,
               *, dry_run: bool = False) -> dict:
    """Observe one frozen contribution; never restore a ref or repeat an effect."""
    if str(config.approval.get("gate") or "") != "github_pr":
        return {**result, "ok": True, "status": "waiting_policy_adapter"}
    import re
    repository = _repository(root)
    _, owner, name = repository.split("/")
    base = str(config.approval.get("default_branch") or "main")
    result.update(discovery={"repository": repository, "branch": branch,
        "coverage": "current_configured_proposal_namespace_only; no absence-of-effect guarantee"},
        served_adoption_verified=False)
    listed_head = None
    if number is not None and (isinstance(number, bool) or not str(number).isdigit() or int(number) < 1):
        raise ContributionError("invalid_pr")
    if number is None:
        try:
            matches = _gh(root, "pr", "list", "--repo", repository, "--head", branch,
                          "--state", "all", "--limit", "100", "--json", "number,headRefOid")
        except (ContributionError, ValueError, TypeError) as exc:
            raise ContributionError("pr_discovery_unknown") from exc
        if not isinstance(matches, list):
            raise ContributionError("pr_discovery_unknown")
        if len(matches) > 1:
            raise ContributionError("pr_discovery_ambiguous")
        if matches:
            if not isinstance(matches[0], dict):
                raise ContributionError("pr_discovery_unknown")
            number, listed_head = matches[0].get("number"), matches[0].get("headRefOid")
            if (not isinstance(number, int) or isinstance(number, bool) or number < 1
                or not re.fullmatch(r"[0-9a-f]{40}", str(listed_head or ""))):
                raise ContributionError("pr_discovery_unknown")
    try:
        pr = _pr(root, number, repository) if number is not None else None
    except (ContributionError, ValueError, TypeError) as exc:
        raise ContributionError("pr_observation_unknown") from exc
    if number is not None and not isinstance(pr, dict):
        raise ContributionError("pr_observation_unknown")
    if pr is not None:
        if (not isinstance(pr, dict) or pr.get("number") != int(number)
            or pr.get("headRefName") != branch or pr.get("baseRefName") != base
            or pr.get("isCrossRepository") is not False
            or not isinstance(pr.get("headRepository"), dict)
            or not isinstance(pr.get("headRepositoryOwner"), dict)
            or (pr.get("headRepository") or {}).get("name") != name
            or not isinstance(pr["headRepositoryOwner"].get("login"), str)
            or pr["headRepositoryOwner"]["login"].lower() != owner.lower()
            or not re.fullmatch(r"[0-9a-f]{40}", str(pr.get("headRefOid") or ""))
            or (listed_head is not None and listed_head != pr["headRefOid"])):
            raise ContributionError("pr_identity_conflict")
        result["observed_pr"] = {"number": pr["number"], "state": pr.get("state")}
        if pr.get("state") == "MERGED":
            result.update(remote_merged=True, source_commit=_merge_oid(pr))
    local, remote = _candidate(root, branch), _remote_branch(root, branch)
    identities = {x for x in (local, remote, pr["headRefOid"] if pr else None) if x is not None}
    if len(identities) > 1:
        raise ContributionError("proposal_ref_identity_conflict")
    if not identities:
        return {**result, "status": "unknown", "error": "contribution_effect_not_observed"}
    expected = identities.pop()
    try:
        if dry_run:
            commit = _candidate_ref(root, expected + "^{commit}")
            if commit != expected:
                raise ContributionError("proposal_object_not_retained_for_dry_run_unknown")
        elif remote:
            commit = _fetch_remote_ref(root, f"refs/heads/{branch}", expected)
        elif local:
            commit = local
        else:
            commit = _fetch_remote_ref(root, f"refs/pull/{pr['number']}/head", expected)
        canonical = _canonical_observation(root, base, dry_run=dry_run)
    except (ContributionError, ValueError, TypeError) as exc:
        if str(exc) == "discovered_ref_identity_changed":
            raise
        raise ContributionError("contribution_object_observation_unknown") from exc
    entry, _ = _entry(root, commit, path, request, material, approved=canonical)
    result.update(**_proposal_manifest(root, commit),
                  coverage=C3_COVERAGE if entry["contribution"].get("log_format") else COVERAGE)
    if _repository(root) != repository:
        raise ContributionError("origin_identity_changed")
    result.update(proposal_commit=commit, proposal_validated=True)
    if pr is None:
        return {**result, "ok": True, "status": "published_ref_no_pr_observed" if remote else "prepared_ref_no_pr_observed"}
    # Re-read the same PR after object acquisition; separate observations must
    # not be presented as a single atomic remote transaction.
    try:
        current = _pr(root, pr["number"], repository)
    except (ContributionError, ValueError, TypeError) as exc:
        raise ContributionError("pr_observation_unknown") from exc
    identity_fields = ("number", "headRefOid", "headRefName", "baseRefName", "headRepository", "headRepositoryOwner", "isCrossRepository")
    if not isinstance(current, dict):
        raise ContributionError("pr_observation_unknown")
    if any(current.get(k) != pr.get(k) for k in identity_fields):
        raise ContributionError("pr_identity_changed_during_reconciliation")
    result.update(pr=current)
    if current.get("state") == "MERGED":
        result.update(remote_merged=True, source_commit=_merge_oid(current))
        return {**result, **_canonical_readback(root, config, current, path, commit, request, material,
                                               dry_run=dry_run), "ok": True}
    if current.get("state") == "CLOSED":
        return {**result, "ok": True, "status": "closed_unmerged_pr", "pr_state": "CLOSED"}
    if current.get("state") == "OPEN":
        return {**result, "ok": True, "status": "waiting_pr", "pr_state": "OPEN"}
    raise ContributionError("pr_state_observation_unknown")


def _canonical_readback(root: Path, config: WikiConfig, pr: dict, path: str,
                        candidate: str, request: dict, material: str,
                        *, dry_run: bool = False) -> dict:
    merge = _merge_oid(pr)
    if not merge:
        raise ContributionError("merge_readback_unavailable")
    # A fetch reads canonical Git source; it does not switch or update the
    # application's worktree or imply that a reader/service adopted it.
    branch = str(config.approval.get("default_branch") or "main")
    remote_head = _canonical_observation(root, branch, dry_run=dry_run)
    _git(root, "merge-base", "--is-ancestor", merge, remote_head)
    expected = _blob(root, candidate, path)
    _, merged_text = _entry(root, merge, path, request, material, approved=remote_head)
    if merged_text != expected:
        raise ContributionError("merged_body_readback_mismatch")
    current_text = _blob(root, remote_head, path)
    p = subprocess.run(["git", "merge-base", "--is-ancestor", merge, "HEAD"], cwd=root,
                       capture_output=True)
    target, _ = _contained_action_path(root, path)
    local = p.returncode == 0 and target.read_text() == current_text and current_text == expected
    log_ref = WikiPaths(root, config).log_page.relative_to(root).as_posix()
    expected_log = _blob(root, candidate, log_ref)
    merged_log, current_log = _blob(root, merge, log_ref), _blob(root, remote_head, log_ref)
    if merged_log != expected_log:
        raise ContributionError("merged_log_readback_mismatch")
    log_path, _ = _contained_action_path(root, log_ref)
    local = local and current_log == expected_log and log_path.read_text() == current_log
    c3 = _c3_policy(root, _git(root, "rev-parse", candidate + "^"))
    files = [{"path": path, "sha256": _sha(current_text)}, {"path": log_ref, "sha256": _sha(current_log)}]
    for p in c3["derived_paths"] if c3 else []:
        expected_metadata = _tracked_regular(root, candidate, p, executable=False)
        if _tracked_regular(root, merge, p, executable=False) != expected_metadata:
            raise ContributionError("merged_metadata_readback_mismatch")
        current_metadata = _tracked_regular(root, remote_head, p, executable=False)
        local_text = _local_file(root, p, mode="100644")
        local = local and current_metadata == expected_metadata and local_text == current_metadata
        files.append({"path": p, "sha256": _sha(current_metadata)})
    return {"status": "adopted_in_checkout" if local else "waiting_worktree_adoption",
            "remote_merged": True, "source_commit": merge, "canonical_head": remote_head,
            "canonical_body_adopted": local, "readback_sha256": _sha(current_text),
            "merged_sha256": _sha(merged_text), "canonical_matches_material": current_text == expected,
            "worktree_adopted": local, "served_adoption_verified": False,
            "coverage": (C3_COVERAGE if c3 else COVERAGE) + "; Git source and selected checkout only",
            "readback_files": sorted(files, key=lambda f: f["path"])}


def _integration_sources(root: Path, config: WikiConfig, commit: str, entry: dict, path: str,
                         c3: dict | None, *, dry_run: bool, extra_paths: list[str] | None = None) -> None:
    parent = _git(root, "rev-parse", commit + "^")
    current = _local_file(root, path, mode=_mode(root, parent, path))
    if _sha(current) != entry["before_sha256"]:
        raise ContributionError("source_changed_since_prepare: reconcile required")
    canonical = _canonical_observation(root, str(config.approval.get("default_branch") or "main"), dry_run=dry_run)
    if _blob(root, canonical, path) != _blob(root, parent, path) or _mode(root, canonical, path) != _mode(root, parent, path):
        raise ContributionError("canonical_action_changed: reconcile required")
    log_ref = WikiPaths(root, config).log_page.relative_to(root).as_posix()
    protected = _protected_inputs(root, parent, c3)
    protected[log_ref] = (_blob(root, parent, log_ref), _mode(root, parent, log_ref))
    for p in extra_paths or []:
        protected[p] = (_tracked_regular(root, parent, p), _mode(root, parent, p))
    for p, (text, mode) in protected.items():
        if _blob(root, canonical, p) != text or _mode(root, canonical, p) != mode:
            label = "policy" if p == "wiki.config.yaml" else "log" if p == log_ref else "consumer_input"
            raise ContributionError("canonical_" + label + "_changed: reconcile required")
        _local_file(root, p, text, mode=mode)


def run_contribution(root: Path, config: WikiConfig, operation: str, payload: dict,
                     *, dry_run: bool = True) -> dict:
    """Trusted local CLI/API; adapters never supply executable gate commands."""
    result: dict[str, Any] = {"ok": False, "operation": operation,
                              "canonical_body_adopted": False, "coverage": COVERAGE}
    try:
        # The application's config object can be cached. Always reload the
        # actual policy rather than promoting with stale permissions.
        config = load_config(root)
        request = payload.get("request")
        path, material, branch = _request(config, request)
        result.update(effect_key=request["effect_key"], task_ref=request["task_ref"],
                      material_sha256=material, branch=branch)
        if dry_run:
            result["dry_run"] = True
        if operation not in OPERATIONS:
            raise ContributionError("unknown_contribution_operation")
        if operation == "prepare_contribution":
            prepared = _prepare(root, config, request, payload.get("review"), dry_run=dry_run)
            return {**result, **prepared, "ok": True,
                    **({"status": "dry_run", "validation_status": prepared["status"],
                        "gates_not_run": True} if dry_run else {})}
        if operation == "reconcile_contribution":
            return _reconcile(root, config, request, path, material, branch, payload.get("pr"), result,
                              dry_run=dry_run)
        commit = _candidate(root, branch)
        if not commit:
            raise ContributionError("prepare_required")
        entry, _ = _entry(root, commit, path, request, material)
        result.update(**_proposal_manifest(root, commit),
                      coverage=C3_COVERAGE if entry["contribution"].get("log_format") else COVERAGE)
        if operation == "publish_contribution":
            if str(config.approval.get("gate") or "") != "github_pr":
                return {**result, "ok": True, "status": "waiting_policy_adapter"}
            repository = _repository(root)
            if dry_run:
                return {**result, "ok": True, "status": "dry_run", "validation_status": "ready_to_publish",
                        "proposal_commit": commit, "repository": repository}
            _git(root, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
            prs = _gh(root, "pr", "list", "--repo", _repository(root), "--head", branch, "--state", "all", "--json", "number,headRefOid,url")
            if prs:
                if len(prs) != 1 or prs[0]["headRefOid"] != commit:
                    raise ContributionError("pr_identity_conflict")
                return {**result, "ok": True, "status": "awaiting_review", "pr": prs[0]}
            base_branch = str(config.approval.get("default_branch") or "main")
            url = _run(root, "gh", "pr", "create", "--repo", _repository(root), "--draft", "--base", base_branch,
                       "--head", branch, "--title", "wiki: reviewed action contribution",
                       "--body", "One reviewed action body; material " + material)
            return {**result, "ok": True, "status": "awaiting_review", "pr_url": url}
        if str(config.approval.get("gate") or "") != "github_pr":
            return {**result, "ok": True, "status": "waiting_policy_adapter"}
        pr = _pr(root, payload.get("pr"))
        if pr.get("headRefOid") != commit or pr.get("baseRefName") != str(config.approval.get("default_branch") or "main"):
            raise ContributionError("pr_identity_conflict")
        if pr.get("state") == "MERGED":
            result.update(remote_merged=True, source_commit=_merge_oid(pr))
            return {**result, **_canonical_readback(root, config, pr, path, commit, request, material,
                                                   dry_run=dry_run), "ok": True}
        if operation != "integrate_contribution":
            raise ContributionError("unknown_contribution_operation")
        if str(config.approval.get("gate") or "") != "github_pr":
            return {**result, "ok": True, "status": "waiting_policy_adapter"}
        if pr.get("isDraft") or pr.get("reviewDecision") == "CHANGES_REQUESTED":
            return {**result, "ok": True, "status": "waiting_pr_review"}
        if not isinstance(config.approval.get("require_human_review", False), bool):
            raise ContributionError("invalid_human_review_policy")
        local_validation = _local_validation(config)
        checks = pr.get("statusCheckRollup") or []
        if pr.get("state") != "OPEN" or (not local_validation and not checks) or any(
            not isinstance(c, dict) or (c.get("conclusion") or c.get("state")) != "SUCCESS" for c in checks):
            return {**result, "ok": True, "status": "waiting_ci_or_pr", "gate_receipts": checks}
        # Human review is required only when the actual consumer says so.
        # A trusted adapter's independent report is never counted as human.
        if config.approval.get("require_human_review") is True:
            approved = [r for r in pr.get("reviews", []) if r.get("state") == "APPROVED"
                        and r.get("commit", {}).get("oid") == commit]
            if not approved:
                return {**result, "ok": True, "status": "waiting_human_review"}
            # GitHub enforces reviewer permissions and dismissal policy. Query
            # account type explicitly rather than treating bots as humans.
            if not any(_gh(root, "api", "--hostname", _repository(root).split("/")[0], "users/" + r["author"]["login"]).get("type") == "User" for r in approved):
                return {**result, "ok": True, "status": "waiting_human_review"}
        parent = _git(root, "rev-parse", commit + "^")
        c3 = _c3_policy(root, parent)
        _integration_sources(root, config, commit, entry, path, c3, dry_run=dry_run)
        if entry["contribution"]["review"]["material_sha256"] != material:
            raise ContributionError("exact_material_review_required")
        manifest = _proposal_manifest(root, commit)
        head_review = _head_review(request, material, commit, payload.get("head_review"),
            candidate_files=manifest["candidate_files"] if c3 or local_validation else None)
        # The independent report covers the generated receipt/log commit, not
        # just input material. Keep it external to avoid a circular commit hash.
        if _candidate(root, branch) != commit:
            raise ContributionError("proposal_head_changed_after_review")
        result.update(head_review=head_review, head_review_sha256=digest(head_review), **manifest)
        if dry_run:
            return {**result, "ok": True, "status": "dry_run",
                    "validation_status": "ready_for_local_validation" if local_validation else "ready_to_integrate",
                    **({"local_gates_not_run": True} if local_validation else {})}
        if local_validation:
            validation = _validate_local_candidate(root, commit)
            result.update(validation_receipt=validation, validation_receipt_sha256=digest(validation))
            _integration_sources(root, config, commit, entry, path, c3, dry_run=False,
                                 extra_paths=[f["path"] for f in validation["command_sources"]])
        # Revalidate both the actual branch and GitHub's current draft/review/
        # checks immediately before the effect, after potentially long gates.
        if _candidate(root, branch) != commit:
            raise ContributionError("proposal_head_changed_after_validation")
        fresh = _pr(root, pr["number"])
        fields = ("number", "headRefOid", "headRefName", "baseRefName", "headRepository", "headRepositoryOwner", "isCrossRepository")
        if not isinstance(fresh, dict) or any(fresh.get(k) != pr.get(k) for k in fields):
            raise ContributionError("pr_identity_changed_after_validation")
        fresh_checks = fresh.get("statusCheckRollup") or []
        if (fresh.get("state") != "OPEN" or fresh.get("isDraft")
            or fresh.get("reviewDecision") == "CHANGES_REQUESTED"
            or (not local_validation and not fresh_checks)
            or any(not isinstance(c, dict) or (c.get("conclusion") or c.get("state")) != "SUCCESS" for c in fresh_checks)
            or (config.approval.get("require_human_review") is True and fresh.get("reviews") != pr.get("reviews"))):
            return {**result, "ok": True, "status": "waiting_ci_or_pr", "gate_receipts": fresh_checks}
        # GitHub's match-head CAS guards the only canonical write. Reconcile
        # first on the next invocation after any transport failure/UNKNOWN.
        _run(root, "gh", "pr", "merge", str(pr["number"]), "--repo", _repository(root), "--merge", "--match-head-commit", commit)
        confirmed = _pr(root, pr["number"])
        if confirmed.get("state") != "MERGED" or confirmed.get("headRefOid") != commit:
            raise ContributionError("merge_outcome_unknown: reconcile")
        result.update(remote_merged=True, source_commit=_merge_oid(confirmed))
        return {**result, **_canonical_readback(root, config, confirmed, path, commit, request, material),
                "ok": True, "gate_receipts": checks}
    except (ContributionError, ActionTransitionError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        message = (exc.code if isinstance(exc, ActionTransitionError) else str(exc) if isinstance(exc, ContributionError)
                   else "contribution_observation_unknown" if isinstance(exc, (OSError, subprocess.TimeoutExpired))
                   else "invalid_contribution_input")
        details = exc.details if isinstance(exc, ContributionError) else {}
        return {**result, **details, "error": message, "status": "unknown" if "unknown" in message or result.get("remote_merged") else "refused"}
