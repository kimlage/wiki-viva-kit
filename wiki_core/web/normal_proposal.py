"""Bounded documentary proposal preparation under a live local session.

The model returns inert material. Native writers and fixed deterministic C2
producers run in an isolated staging tree; only their pinned outputs can be
installed. Each actual checkout/Git effect revalidates the live session.
This prepares an ordinary proposal, never publishes or approves it.
"""
from __future__ import annotations

import datetime as dt
import copy
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import yaml
from pathlib import Path
from typing import Any

from wiki_core.action_transition import integrate_action_body, transition_action_page
from wiki_core.config import WikiConfig, load_config
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.source_integrity import _worktree_entry
from wiki_core.web.admin.sessions import AdminSessionManager
from wiki_core.web.git_workflows import CHECKOUT_LOCK, run_git_workflow

SCHEMA = "wiki_normal_proposal.v1"
MAX_MATERIAL_BYTES = 8 * 1024 * 1024
MAX_STAGING_BYTES = 128 * 1024 * 1024
C2_IDS = ("input_stage", "operation", "operational_pass")


class ProposalError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _safe(root: Path, ref: str) -> Path:
    path = Path(ref)
    if (not isinstance(ref, str) or not ref or path.is_absolute()
            or path.as_posix() != ref or ".." in path.parts or "\\" in ref
            or any(ord(c) < 32 for c in ref)
            or any(p.startswith(".") or p.lower() in {"raw", "secrets", "credentials"} for p in path.parts)):
        raise ProposalError("proposal_path_not_eligible")
    target = root / path
    for parent in [target, *target.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ProposalError("proposal_symlink_not_eligible")
    return target


def _bytes(root: Path, ref: str) -> bytes | None:
    path = _safe(root, ref)
    if not path.exists():
        return None
    if not path.is_file():
        raise ProposalError("proposal_requires_regular_file")
    return _worktree_entry(root, "100644", ref)


def _closed(value: Any, required: set[str], optional: set[str] = frozenset()) -> None:
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise ProposalError("proposal_invalid_material_shape")


def _document_target(root: Path, config: WikiConfig, ref: str) -> Path:
    path = _safe(root, ref)
    paths = WikiPaths(root, config)
    if (not any(path.is_relative_to(base) for base in (paths.memory_root, paths.references_root))
            or path.suffix not in {".md", ".json", ".txt", ".xml", ".log"}):
        raise ProposalError("proposal_document_target_not_eligible")
    return path


def load_material(root: Path, config: WikiConfig, params: dict) -> tuple[dict, str]:
    if os.name != "posix":
        raise ProposalError("proposal_requires_posix")
    _closed(params, {"material_path", "material_sha256"})
    path = _safe(root, params["material_path"])
    if not path.is_relative_to(WikiPaths(root, config).derived_root):
        raise ProposalError("proposal_material_must_be_derived")
    data = _bytes(root, params["material_path"])
    if data is None or len(data) > MAX_MATERIAL_BYTES or _sha(data) != params["material_sha256"]:
        raise ProposalError("proposal_material_digest_mismatch")
    from wiki_core.action_transition import _assert_no_secrets
    _assert_no_secrets(data.decode("utf-8"))
    material = json.loads(data)
    _closed(material, {"schema_version", "base_head", "branch", "action", "documents", "c2", "generated_at", "commit_message"},
            {"freshness_pointer"})
    if material["schema_version"] != SCHEMA:
        raise ProposalError("proposal_schema_unsupported")
    instant = dt.datetime.fromisoformat(material["generated_at"].replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ProposalError("proposal_generation_timezone_required")
    if (not re.fullmatch(r"[0-9a-f]{40,64}", material["base_head"])
            or material["base_head"] != _git(root, "rev-parse", "HEAD")
            or material["branch"] != _git(root, "branch", "--show-current")
            or material["branch"] == str(config.approval.get("default_branch") or "main")
            or not material["branch"].startswith(str(config.approval.get("branch_prefix") or "wiki/"))):
        raise ProposalError("proposal_base_or_branch_mismatch")
    if (not isinstance(material["c2"], list) or len(set(material["c2"])) != len(material["c2"])
            or not set(material["c2"]) <= set(C2_IDS)):
        raise ProposalError("proposal_unknown_generator")
    if not isinstance(material["documents"], list) or len(material["documents"]) > 128:
        raise ProposalError("proposal_invalid_documents")
    message = material["commit_message"]
    if not isinstance(message, str) or len(message.strip()) < 8 or "\n" in message or "\r" in message:
        raise ProposalError("proposal_invalid_commit_message")
    return material, _sha(data)


def _render_c2(root: Path, config: WikiConfig, ids: list[str], generated_at: str, effect_runner=None) -> dict[str, bytes]:
    """Fixed producers only. The request cannot provide argv or import paths."""
    paths = WikiPaths(root, config)
    result = {}
    instant = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    for producer in C2_IDS:
        if producer not in ids:
            continue
        def generate():
            if producer == "input_stage":
                from wiki_core.input_stage import write_input_stage
                write_input_stage(root, config, generated_at=instant.date(), if_changed=True)
                return (paths.input_stage_page, paths.input_stage_catalog)
            if producer == "operational_pass":
                from wiki_core.operational_pass import build_operational_pass_page
                paths.operational_pass_page.parent.mkdir(parents=True, exist_ok=True)
                paths.operational_pass_page.write_text(build_operational_pass_page(
                    root, config, updated_at=instant.date().isoformat()), encoding="utf-8")
                return (paths.operational_pass_page,)
            from scripts.wiki_operation_compile import build_page
            paths.operation_page.parent.mkdir(parents=True, exist_ok=True)
            paths.operation_page.write_text(build_page(root, config, generated_at=instant), encoding="utf-8")
            return (paths.operation_page,)
        outputs = effect_runner(generate) if effect_runner else generate()
        for path in outputs:
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _write_action(root: Path, action: dict) -> None:
    ref = action["page_ref"]
    if _bytes(root, ref) is None or _sha(_bytes(root, ref)) != action["expected_sha256"]:
        raise ProposalError("proposal_action_revision_mismatch")
    if "body" in action:
        integrate_action_body(root, ref, action["body"], expected_sha256=action["expected_sha256"],
                              contribution=action["contribution"], recorded_at=action["recorded_at"])
    if "transition" in action:
        transition_action_page(root, ref, expected_sha256=_sha((root / ref).read_bytes()), **action["transition"])


def preview_proposal(root: Path, config: WikiConfig, params: dict, *, effect_runner=None,
                     expected_readset_sha256: str | None = None) -> dict:
    material, material_sha = load_material(root, config, params)
    paths = WikiPaths(root, config)
    readset: dict[str, bytes | None] = {}
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    for ref in filter(None, names):
        candidate = root / ref
        if (candidate.is_relative_to(paths.memory_root) or candidate.is_relative_to(paths.references_root)
                or (len(Path(ref).parts) == 1 and ref.startswith("wiki") and ref.endswith(".yaml"))):
            readset[ref] = _bytes(root, ref)
            if readset[ref] is None:
                raise ProposalError("proposal_tracked_input_missing")
    declared_docs = {d.get("path") for d in material["documents"] if isinstance(d, dict)}
    generated_refs = {p.relative_to(root).as_posix() for p in (
        paths.input_stage_page, paths.operational_pass_page, paths.operation_page)}
    for page in paths.memory_root.rglob("*.md"):
        ref = page.relative_to(root).as_posix()
        if ref not in readset:
            if ref not in declared_docs | generated_refs:
                raise ProposalError("proposal_untracked_memory_input")
            readset[ref] = _bytes(root, ref)
    if "operation" in material["c2"]:
        # These are real read inputs of the existing cockpit compiler, not a
        # snapshot of all derived caches. Pin both score-ledger alternatives,
        # every context request and the exact result keys those requests read.
        from wiki_core.consolidate import REQUEST_SUFFIX
        from wiki_core.score.karma import EVENTS_FILENAME, EVENTS_MIRROR_FILENAME
        for filename in (EVENTS_FILENAME, EVENTS_MIRROR_FILENAME):
            ref = (paths.derived_root / filename).relative_to(root).as_posix()
            readset[ref] = _bytes(root, ref)
        for request in sorted(paths.extraction_events.glob("*" + REQUEST_SUFFIX)):
            ref = request.relative_to(root).as_posix()
            readset[ref] = _bytes(root, ref)
            try:
                value = json.loads(readset[ref])
            except (ValueError, TypeError):
                continue  # The native producer also ignores malformed requests.
            if not isinstance(value, dict) or str(value.get("source_id") or "").startswith("query-"):
                continue
            for chunk in value.get("chunks") or []:
                if not isinstance(chunk, dict):
                    raise ProposalError("proposal_invalid_c2_request")
                key = chunk.get("cache_key")
                if not key:
                    continue
                if not isinstance(key, str) or Path(key).name != key or key in {".", ".."}:
                    raise ProposalError("proposal_unsafe_c2_cache_key")
                ref = (paths.llm_cache / (key + ".json")).relative_to(root).as_posix()
                readset[ref] = _bytes(root, ref)
    cache = paths.input_stage_catalog.relative_to(root).as_posix()
    readset[cache] = _bytes(root, cache)
    action = material["action"]
    _closed(action, {"page_ref", "page_id", "effect_key", "run_id", "expected_sha256"},
            {"body", "contribution", "recorded_at", "transition"})
    action_ref = action["page_ref"]
    action_path = _safe(root, action_ref)
    if not action_path.is_relative_to(paths.actions_dir):
        raise ProposalError("proposal_action_outside_actions")
    readset[action_ref] = _bytes(root, action_ref)
    if readset[action_ref] is None or _sha(readset[action_ref]) != action["expected_sha256"]:
        raise ProposalError("proposal_action_revision_mismatch")
    for name in ("page_id", "effect_key", "run_id"):
        value = action[name]
        if (not isinstance(value, str) or not value or value.strip() != value or len(value) > 256
                or any(ord(c) < 32 for c in value)):
            raise ProposalError("proposal_invalid_canonical_identity")
    frontmatter, _ = parse_frontmatter(action_path)
    if frontmatter.get("page_id") != action["page_id"] or not action["effect_key"] or not action["run_id"]:
        raise ProposalError("proposal_canonical_identity_mismatch")
    if "body" in action and not action.get("recorded_at"):
        raise ProposalError("proposal_writer_requires_recorded_at")
    if "body" in action and (not isinstance(action.get("contribution"), dict)
            or action["contribution"].get("effect_key") != action["effect_key"]
            or action["contribution"].get("run_id") != action["run_id"]):
        raise ProposalError("proposal_contribution_effect_mismatch")
    c2_targets = {paths.input_stage_page, paths.operational_pass_page, paths.operation_page}
    doc_refs = set()
    for doc in material["documents"]:
        _closed(doc, {"path", "before_sha256", "after_text"})
        ref = doc["path"]
        target = _document_target(root, config, ref)
        if ref in doc_refs or target in c2_targets or ref == action_ref:
            raise ProposalError("proposal_duplicate_or_generated_target")
        doc_refs.add(ref)
        before = _bytes(root, ref)
        readset[ref] = before
        if (None if before is None else _sha(before)) != doc["before_sha256"]:
            raise ProposalError("proposal_document_preimage_mismatch")
        if not isinstance(doc["after_text"], str):
            raise ProposalError("proposal_document_requires_text")
        if target.suffix == ".md":
            from wiki_core.action_transition import _parse_document
            try:
                after_fm, _ = _parse_document(doc["after_text"])
            except ValueError:
                after_fm = {}
            if after_fm.get("page_type") == "action":
                raise ProposalError("proposal_action_requires_native_writer")
        if before is not None and target.suffix == ".md":
            fm, _ = parse_frontmatter(target)
            if fm.get("page_type") == "action":
                raise ProposalError("proposal_action_requires_native_writer")
        if target == paths.log_page and (before is None or not doc["after_text"].encode().startswith(before)):
            raise ProposalError("proposal_log_must_be_append_only")
    pointer = material.get("freshness_pointer")
    if pointer is not None:
        _closed(pointer, {"before_sha256", "freshness_base", "freshness_records"})
        ref = "wiki.config.yaml"
        before = _bytes(root, ref)
        readset[ref] = before
        if before is None or _sha(before) != pointer["before_sha256"]:
            raise ProposalError("proposal_config_preimage_mismatch")
        if not re.fullmatch(r"[0-9a-f]{40,64}", pointer["freshness_base"]):
            raise ProposalError("proposal_invalid_freshness_base")
        _document_target(root, config, pointer["freshness_records"])
    if sum(len(v) for v in readset.values() if v is not None) > MAX_STAGING_BYTES:
        raise ProposalError("proposal_staging_budget_exceeded")
    for target in c2_targets:
        ref = target.relative_to(root).as_posix()
        readset.setdefault(ref, _bytes(root, ref))
    readset_sha256 = _sha(json.dumps({ref: None if data is None else _sha(data)
                                    for ref, data in sorted(readset.items())}, sort_keys=True).encode())
    if expected_readset_sha256 is not None and readset_sha256 != expected_readset_sha256:
        raise ProposalError("proposal_planned_readset_changed")
    with tempfile.TemporaryDirectory(prefix="wiki-normal-proposal-") as folder:
        shadow = Path(folder)
        for ref, data in readset.items():
            if data is not None:
                dest = shadow / ref
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        outputs = {}
        for doc in material["documents"]:
            ref = doc["path"]
            (shadow / ref).parent.mkdir(parents=True, exist_ok=True)
            (shadow / ref).write_text(doc["after_text"], encoding="utf-8")
            outputs[ref] = (shadow / ref).read_bytes()
        if "transition" in action:
            transition = action["transition"]
            _closed(transition, {"next_state", "recorded_at"},
                    {"reason", "next_action", "blocked_by", "blocker_reason", "completion_receipt", "cancellation_receipt"})
        if effect_runner:
            effect_runner(lambda: _write_action(shadow, action))
        else:
            _write_action(shadow, action)
        outputs[action_ref] = (shadow / action_ref).read_bytes()
        if pointer is not None:
            # Typed pointer update only; no arbitrary YAML/config replacement.
            text = readset["wiki.config.yaml"].decode()
            for key in ("freshness_base", "freshness_records"):
                text, count = re.subn(r"(?m)^  " + key + r":.*$", "  " + key + ": " + pointer[key], text)
                if count != 1:
                    raise ProposalError("proposal_freshness_pointer_not_unique")
            expected_config = copy.deepcopy(yaml.safe_load(readset["wiki.config.yaml"]))
            if not isinstance(expected_config.get("audit"), dict):
                raise ProposalError("proposal_audit_pointer_not_configured")
            for key in ("freshness_base", "freshness_records"):
                expected_config["audit"][key] = pointer[key]
            if yaml.safe_load(text) != expected_config:
                raise ProposalError("proposal_config_change_outside_pointer")
            (shadow / "wiki.config.yaml").write_text(text, encoding="utf-8")
            outputs["wiki.config.yaml"] = text.encode()
        outputs.update(_render_c2(shadow, load_config(shadow), material["c2"], material["generated_at"], effect_runner))
    for ref in outputs:
        if ref not in readset:
            readset[ref] = _bytes(root, ref)
    from wiki_core.action_transition import _assert_no_secrets
    for data in outputs.values():
        _assert_no_secrets(data.decode())
    changed = {ref: data for ref, data in outputs.items() if data != readset.get(ref)}
    if not changed:
        raise ProposalError("proposal_empty_delta")
    pinned = {ref: _sha(data) for ref, data in sorted(changed.items())}
    return {"material": material, "material_sha256": material_sha, "readset": readset,
            "outputs": changed, "readset_sha256": readset_sha256,
            "output_sha256": _sha(json.dumps(pinned, sort_keys=True).encode())}


def _install(root: Path, ref: str, before: bytes | None, after: bytes) -> None:
    """Pin every directory; never follow a swapped parent or final symlink."""
    from wiki_core.source_integrity import _regular_bytes
    _safe(root, ref)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    opened = [os.open(root.resolve(strict=True), flags)]
    temporary = ".wiki-proposal-" + secrets.token_hex(12)
    created = False
    try:
        for part in Path(ref).parts[:-1]:
            try:
                directory = os.open(part, flags, dir_fd=opened[-1])
            except FileNotFoundError:
                os.mkdir(part, mode=0o755, dir_fd=opened[-1])
                directory = os.open(part, flags, dir_fd=opened[-1])
            opened.append(directory)
        parent, name = opened[-1], Path(ref).name
        try:
            actual, _ = _regular_bytes(parent, name)
        except FileNotFoundError:
            actual = None
        if actual != before:
            raise ProposalError("proposal_effect_preimage_changed")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=parent)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        created = False
        try:
            os.fsync(parent)
        except OSError:
            # The replace already happened. Never describe this as zero effect.
            pass
    finally:
        if created:
            os.unlink(temporary, dir_fd=opened[-1])
        for directory in reversed(opened):
            os.close(directory)


def prepare_proposal(root: Path, config: WikiConfig, params: dict, *, expected_output_sha256: str,
                     expected_readset_sha256: str,
                     manager: AdminSessionManager, token: str, session_id: str,
                     dry_run: bool = False) -> dict:
    """Prepare the real local proposal. No provider calls or implicit grants."""
    with CHECKOUT_LOCK:
        def effect(call):
            admitted = manager.execute_current(token, session_id, ("git.propose", "gates.run"), call)
            if not admitted.get("ok"):
                raise ProposalError(str(admitted["error_code"]))
            return admitted["result"]

        # C2 runs outside the session mutex, registered as in flight. A lock
        # during one producer prevents the next producer and installation.
        effect(lambda: None)
        preview = preview_proposal(root, config, params, effect_runner=effect,
                                   expected_readset_sha256=expected_readset_sha256)
        if preview["output_sha256"] != expected_output_sha256:
            raise ProposalError("proposal_generated_material_changed")
        if dry_run:
            return {"output": {"prepared": False, "dry_run": True}, "affected_paths": []}
        for ref, before in preview["readset"].items():
            if _bytes(root, ref) != before:
                raise ProposalError("proposal_readset_changed")
        if _git(root, "diff", "--cached", "--name-only"):
            raise ProposalError("proposal_index_must_be_empty")
        applied: list[str] = []
        started_paths: list[str] = []
        uncertain_git = False
        last_git_result = None

        try:
            for ref, after in preview["outputs"].items():
                if after == preview["readset"].get(ref):
                    continue  # A fixed C2 output can already be current.
                started_paths.append(ref)
                if ref == preview["material"]["action"]["page_ref"]:
                    effect(lambda: _write_action(root, preview["material"]["action"]))
                    if _bytes(root, ref) != after:
                        raise ProposalError("proposal_native_writer_output_changed")
                else:
                    effect(lambda ref=ref, after=after: _install(root, ref, preview["readset"].get(ref), after))
                applied.append(ref)
            tracked_outputs = [ref for ref in applied if not ref.startswith(config.paths["derived_root"] + "/")]
            for operation, payload in (
                ("stage_paths", {"paths": tracked_outputs}),
                ("commit_proposal", {"message": preview["material"]["commit_message"]}),
            ):
                if operation == "commit_proposal":
                    staged = set(_git(root, "diff", "--cached", "--name-only").splitlines())
                    if staged != set(tracked_outputs):
                        raise ProposalError("proposal_staged_set_changed")
                    for ref in tracked_outputs:
                        entry = _git(root, "ls-files", "--stage", "--", ref)
                        if (not entry.startswith("100644 ") or
                                subprocess.check_output(["git", "show", ":" + ref], cwd=root) != preview["outputs"][ref]):
                            raise ProposalError("proposal_staged_bytes_changed")
                if (_git(root, "rev-parse", "HEAD") != preview["material"]["base_head"] or
                        _git(root, "branch", "--show-current") != preview["material"]["branch"]):
                    raise ProposalError("proposal_git_base_changed")
                result = effect(lambda: run_git_workflow(root, config, operation, payload, dry_run=False))
                last_git_result = result
                if not result.get("ok"):
                    uncertain_git = bool(result.get("outcome_uncertain"))
                    raise ProposalError("proposal_git_effect_failed")
        except Exception as exc:  # An interrupted effect may already have written.
            uncertain = []
            for ref in started_paths:
                try:
                    if _bytes(root, ref) != preview["readset"].get(ref) and ref not in applied:
                        applied.append(ref)
                except (ValueError, OSError):
                    uncertain.append(ref)
            return {"output": {"prepared": False, "error_code": getattr(exc, "code", "proposal_effect_failed"),
                               "partial_paths": applied, "uncertain_paths": uncertain,
                               "outcome_uncertain": uncertain_git,
                               "last_git_result": last_git_result,
                               "canonical_main_changed": False}, "affected_paths": list(dict.fromkeys(applied + uncertain)),
                    "failed": True}
        return {"output": {"prepared": True, "head": _git(root, "rev-parse", "HEAD"),
                           "c2_captured_at": preview["material"]["generated_at"],
                           "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "action_id": preview["material"]["action"]["page_id"],
                           "run_id": preview["material"]["action"]["run_id"],
                           "effect_key": preview["material"]["action"]["effect_key"],
                           "material_sha256": preview["material_sha256"],
                           "output_sha256": preview["output_sha256"], "published": False},
                "affected_paths": applied, "snapshot_invalidated": True}


def publish_proposal(root: Path, config: WikiConfig, *, expected_head: str, operation: str,
                     payload: dict, manager: AdminSessionManager, token: str,
                     session_id: str) -> dict:
    """Perform one fixed provider effect after current-authority validation.

    Local preparation, independent review and complete consumer gates remain
    separate obligations. In particular, receipts/hashes never grant access.
    This adapter has no arbitrary command, contribution-port or job fallback.
    """
    if operation not in {"publish_proposal", "open_draft_pr", "update_draft_pr"}:
        raise ProposalError("proposal_unsupported_provider_operation")
    allowed = set() if operation == "publish_proposal" else {"title", "body"}
    _closed(payload, set(), allowed)
    from wiki_core.action_transition import _assert_no_secrets
    for value in payload.values():
        if not isinstance(value, str):
            raise ProposalError("proposal_provider_text_required")
        _assert_no_secrets(value)
    with CHECKOUT_LOCK:
        from wiki_core.action_contribution import _repository
        from wiki_core.web.git_workflows import _run, _ok_response
        repository = _repository(root)
        fetch_url = _git(root, "remote", "get-url", "origin")
        push_urls = _git(root, "remote", "get-url", "--push", "--all", "origin").splitlines()
        if push_urls != [fetch_url]:
            raise ProposalError("proposal_push_destination_mismatch")
        branch = _git(root, "branch", "--show-current")
        _assert_no_secrets(branch)
        if (not isinstance(expected_head, str) or not re.fullmatch(r"[0-9a-f]{40,64}", expected_head)
                or _git(root, "rev-parse", "HEAD") != expected_head
                or branch == str(config.approval.get("default_branch") or "main")
                or not branch.startswith(str(config.approval.get("branch_prefix") or "wiki/"))):
            raise ProposalError("proposal_git_base_changed")
        def provider_effect():
            if (_repository(root) != repository or _git(root, "rev-parse", "HEAD") != expected_head
                    or _git(root, "remote", "get-url", "--push", "--all", "origin").splitlines() != [fetch_url]):
                raise ProposalError("proposal_git_base_changed")
            def remote_head():
                result = _run(root, ["git", "ls-remote", "--heads", "origin", "refs/heads/" + branch], timeout_seconds=60)
                rows = result.get("stdout", "").splitlines()
                if not result.get("ok") or len(rows) > 1:
                    raise ProposalError("proposal_remote_head_unavailable")
                if rows and (len(rows[0].split()) != 2 or rows[0].split()[1] != "refs/heads/" + branch
                             or not re.fullmatch(r"[0-9a-f]{40,64}", rows[0].split()[0])):
                    raise ProposalError("proposal_remote_head_unavailable")
                return rows[0].split()[0] if rows else None
            def valid_pr(pr):
                return bool(isinstance(pr, dict) and pr.get("headRefOid") == expected_head
                    and pr.get("headRefName") == branch and pr.get("state") == "OPEN"
                    and pr.get("baseRefName") == str(config.approval.get("default_branch") or "main"))
            def dispatch(argv, timeout_seconds):
                try:
                    return _run(root, argv, timeout_seconds=timeout_seconds)
                except Exception:
                    # A process may already have run before decoding fails.
                    # Observation below must reconcile its effect, not retry.
                    return {"ok": False, "returncode": None, "argv": argv,
                            "stderr": "provider outcome requires readback"}
            def prior_pr():
                observation = _run(root, ["gh", "pr", "list", "--repo", repository,
                    "--head", branch, "--base", str(config.approval.get("default_branch") or "main"),
                    "--state", "open", "--json", "url,headRefOid,headRefName,baseRefName,state,title,body"], timeout_seconds=60)
                try:
                    values = json.loads(observation.get("stdout") or "null")
                    if not observation.get("ok") or not isinstance(values, list) or len(values) > 1:
                        raise ValueError()
                    if values and not valid_pr(values[0]):
                        raise ProposalError("proposal_provider_head_mismatch")
                    return values[0] if values else None
                except (ValueError, TypeError) as exc:
                    raise ProposalError("proposal_provider_observation_unavailable") from exc
            before_head = remote_head()
            if operation == "publish_proposal":
                if before_head == expected_head:
                    return {"ok": True, "status": "observed_published", "head": expected_head,
                            "outcome_uncertain": False, "new_provider_effect": False}
                result = dispatch(["git", "push", "origin", expected_head + ":refs/heads/" + branch], 180)
            else:
                if before_head != expected_head:
                    raise ProposalError("proposal_remote_head_mismatch")
                before_pr = prior_pr()
                if operation == "update_draft_pr" and before_pr is None:
                    raise ProposalError("proposal_provider_pr_missing")
                if operation == "open_draft_pr" and before_pr:
                    if (before_pr.get("title") != str(payload.get("title") or branch)
                            or before_pr.get("body") != str(payload.get("body") or "Prepared documentary proposal.")):
                        raise ProposalError("proposal_existing_pr_requires_reconciliation")
                    return {"ok": True, "status": "observed_pr", "head": expected_head,
                            "pr_url": before_pr.get("url"), "outcome_uncertain": False,
                            "new_provider_effect": False, "served_adoption_verified": False}
                body = str(payload.get("body") or "Prepared documentary proposal.")
                from wiki_core.action_transition import _assert_no_secrets
                _assert_no_secrets(body)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md", prefix="wiki-pr-body-") as file:
                    file.write(body)
                    file.flush()
                    argv = ["gh", "pr", "create" if operation == "open_draft_pr" else "edit",
                            *( [] if operation == "open_draft_pr" else [branch]),
                            "--repo", repository, "--title", str(payload.get("title") or branch), "--body-file", file.name]
                    if operation == "open_draft_pr":
                        argv.extend(["--draft", "--base", str(config.approval.get("default_branch") or "main"), "--head", branch])
                    result = dispatch(argv, 180)
            try:
                after_head = remote_head()
                verified = after_head == expected_head
                observed_pr = None
                if operation != "publish_proposal":
                    readback = _run(root, ["gh", "pr", "view", branch, "--repo", repository,
                        "--json", "url,headRefOid,headRefName,baseRefName,state,title,body"], timeout_seconds=60)
                    observed_pr = json.loads(readback.get("stdout") or "null") if readback.get("ok") else None
                    verified = bool(verified and valid_pr(observed_pr)
                        and observed_pr.get("title") == str(payload.get("title") or branch)
                        and observed_pr.get("body") == str(payload.get("body") or "Prepared documentary proposal."))
            except Exception:
                after_head, observed_pr, verified = None, None, False
            return {**_ok_response(operation, dry_run=False, summary="Provider operation with prepared-head readback", results=[result]),
                    "ok": verified, "outcome_uncertain": not verified, "head": expected_head,
                    "remote_head_before": before_head, "remote_head_after": after_head,
                    "pr_url": observed_pr.get("url") if isinstance(observed_pr, dict) else None,
                    "readback_only_no_provider_lock": True, "served_adoption_verified": False}
        admitted = manager.execute_current(token, session_id, ("git.publish",), provider_effect)
        if not admitted.get("ok"):
            raise ProposalError(admitted["error_code"])
        return admitted["result"]


def committed_config(root: Path, revision: str) -> WikiConfig:
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(revision)):
        raise ProposalError("proposal_invalid_git_revision")
    with tempfile.TemporaryDirectory(prefix="wiki-proposal-policy-") as folder:
        target = Path(folder)
        for ref in _git(root, "ls-tree", "--name-only", revision).splitlines():
            if len(Path(ref).parts) == 1 and ref.startswith("wiki") and ref.endswith(".yaml"):
                (target / ref).write_bytes(subprocess.check_output(["git", "show", revision + ":" + ref], cwd=root))
        return load_config(target)


def promotion_policy(root: Path, params: dict) -> WikiConfig:
    """Only approved code/policy can validate this documentary proposal."""
    approved = params["approved_base"]
    config = committed_config(root, params["expected_head"])
    base_config = committed_config(root, approved)
    default = str(base_config.approval.get("default_branch") or "main")
    if (_git(root, "rev-parse", default) != approved or config.approval != base_config.approval
            or config.paths != base_config.paths):
        raise ProposalError("proposal_approved_policy_mismatch")
    if subprocess.run(["git", "merge-base", "--is-ancestor", approved, params["expected_head"]], cwd=root,
                      capture_output=True).returncode:
        raise ProposalError("proposal_approved_base_mismatch")
    changed = _git(root, "diff", "--name-only", approved, params["expected_head"]).splitlines()
    if not changed:
        raise ProposalError("proposal_empty_delta")
    for ref in changed:
        if ref == "wiki.config.yaml":
            before = subprocess.check_output(["git", "show", approved + ":" + ref], cwd=root).decode()
            after = subprocess.check_output(["git", "show", params["expected_head"] + ":" + ref], cwd=root).decode()
            for key in ("freshness_base", "freshness_records"):
                value = str(config.audit.get(key) or "")
                if key == "freshness_base" and not re.fullmatch(r"[0-9a-f]{40,64}", value):
                    raise ProposalError("proposal_invalid_freshness_base")
                if key == "freshness_records":
                    _document_target(root, base_config, value)
                before, count = re.subn(r"(?m)^  " + key + r":.*$", "  " + key + ": " + value, before)
                if count != 1:
                    raise ProposalError("proposal_freshness_pointer_not_unique")
            if before != after:
                raise ProposalError("proposal_config_change_outside_pointer")
        else:
            _document_target(root, base_config, ref)
            if not _git(root, "ls-tree", params["expected_head"], "--", ref).startswith("100644 blob "):
                raise ProposalError("proposal_requires_committed_regular_document")
    return config


def promotion_review(root: Path, config: WikiConfig, params: dict) -> dict:
    """Integrity/policy condition only; the live session grants no review."""
    _closed(params, {"expected_head", "approved_base", "pr", "review_path", "review_sha256"})
    config = promotion_policy(root, params)
    path = _safe(root, params["review_path"])
    if not path.is_relative_to(WikiPaths(root, config).derived_root):
        raise ProposalError("proposal_review_must_be_derived")
    raw = _bytes(root, params["review_path"])
    if raw is None or len(raw) > MAX_MATERIAL_BYTES or _sha(raw) != params["review_sha256"]:
        raise ProposalError("proposal_review_digest_mismatch")
    from wiki_core.action_transition import _assert_no_secrets
    _assert_no_secrets(raw.decode())
    review = json.loads(raw)
    _closed(review, {"schema_version", "head", "approved_base", "repository", "author", "reviewer", "decision", "unresolved_findings", "evidence"})
    from wiki_core.action_contribution import _repository
    if (review["schema_version"] != "wiki_normal_review.v1" or review["head"] != params["expected_head"]
            or review["decision"] != "approved" or review["unresolved_findings"] != []
            or not all(isinstance(review[k], str) and review[k].strip() for k in ("author", "reviewer", "evidence"))
            or review["author"].strip() == review["reviewer"].strip()
            or len(params["pr"]) > 12 or not re.fullmatch(r"[1-9][0-9]*", params["pr"])
            or review["repository"] != _repository(root) or review["approved_base"] != params["approved_base"]):
        raise ProposalError("proposal_independent_review_required")
    require_human = config.approval.get("require_human_review", False)
    if not isinstance(require_human, bool):
        raise ProposalError("proposal_invalid_human_review_policy")
    if require_human:
        # This adapter cannot infer a human approval from a local assertion.
        raise ProposalError("proposal_human_review_policy_adapter_required")
    return review


def promote_proposal(root: Path, config: WikiConfig, params: dict, *, manager: AdminSessionManager,
                     token: str, session_id: str) -> dict:
    """Validate immutable approved code/policy, then guard each provider effect."""
    from wiki_core.action_contribution import (_local_integration_gates, _validation_policy,
                                               _integration_pr_wait, _repository, ContributionError)
    from wiki_core.web.git_workflows import _run
    with CHECKOUT_LOCK:
        review = promotion_review(root, config, params)
        config = promotion_policy(root, params)
        expected_head, approved = params['expected_head'], params['approved_base']
        repository = _repository(root)
        _, owner, name = repository.split('/')
        branch = _git(root, 'branch', '--show-current')
        default = str(config.approval.get('default_branch') or 'main')
        if (_git(root, 'rev-parse', 'HEAD') != expected_head or branch == default
                or not branch.startswith(str(config.approval.get('branch_prefix') or 'wiki/'))):
            raise ProposalError('proposal_git_base_changed')
        results, gates = [], []

        def admitted(call, capabilities):
            outcome = manager.execute_current(token, session_id, capabilities, call)
            if not outcome.get('ok'):
                raise ProposalError(outcome['error_code'])
            return outcome['result']

        def observe():
            data = _run(root, ['gh', 'pr', 'view', params['pr'], '--repo', repository, '--json',
                'number,headRefOid,headRefName,baseRefOid,baseRefName,state,isDraft,isCrossRepository,'
                'headRepository,headRepositoryOwner,statusCheckRollup,reviewDecision,reviews,mergeCommit'], timeout_seconds=60)
            try:
                if not data['ok']:
                    raise ValueError()
                value = json.loads(data['stdout'])
                if not isinstance(value, dict):
                    raise ValueError()
                return value
            except (ValueError, TypeError, KeyError) as exc:
                raise ProposalError('proposal_provider_observation_unavailable') from exc

        def identity(pr, *, merged=False):
            if (not isinstance(pr.get('headRepository'), dict)
                    or not isinstance(pr.get('headRepositoryOwner'), dict)
                    or not isinstance(pr.get('isDraft'), bool)
                    or pr.get('number') != int(params['pr']) or pr.get('headRefOid') != expected_head
                    or pr.get('headRefName') != branch or pr.get('baseRefName') != default
                    or pr.get('isCrossRepository') is not False
                    or (pr.get('headRepository') or {}).get('name', '').lower() != name.lower()
                    or (pr.get('headRepositoryOwner') or {}).get('login', '').lower() != owner.lower()
                    or (not merged and pr.get('baseRefOid') != approved)):
                raise ProposalError('proposal_provider_head_mismatch')

        def ready_for_effect(pr, *, allow_draft=False):
            identity(pr)
            waiting = _integration_pr_wait(root, config, {**pr, **({'isDraft': False} if allow_draft else {})},
                                           expected_head, _validation_policy(config))
            if waiting:
                raise ProposalError('proposal_' + waiting['status'])
            promotion_review(root, config, params)
            if (_git(root, 'rev-parse', 'HEAD') != expected_head
                    or _git(root, 'branch', '--show-current') != branch or _repository(root) != repository):
                raise ProposalError('proposal_git_base_changed')

        try:
            pr = observe()
            if pr.get('state') == 'MERGED':
                identity(pr, merged=True)
                if (not isinstance(pr.get('mergeCommit'), dict)
                        or not re.fullmatch(r'[0-9a-f]{40,64}', str(pr['mergeCommit'].get('oid')))):
                    raise ProposalError('proposal_merge_readback_unavailable')
                return {'ok': True, 'status': 'observed_merged', 'head': expected_head,
                        'merge_commit': pr['mergeCommit']['oid'], 'new_provider_effect': False,
                        'served_adoption_verified': False}
            ready_for_effect(pr, allow_draft=True)
            gates = admitted(lambda: _local_integration_gates(root, expected_head,
                effect_runner=lambda call: admitted(call, ('gates.run',)),
                required_policy=_validation_policy(config), record_support_override=True), ('gates.run',))
            pr = observe()
            ready_for_effect(pr, allow_draft=True)
            if pr.get('isDraft'):
                def ready_effect():
                    ready_for_effect(observe(), allow_draft=True)
                    result = None
                    try:
                        result = _run(root, ['gh', 'pr', 'ready', params['pr'], '--repo', repository], timeout_seconds=60)
                        after = observe()
                        identity(after)
                        verified = after.get('state') == 'OPEN' and after.get('isDraft') is False
                    except Exception:
                        verified = False
                    return {'ok': verified, 'stage': 'pr.ready', 'result': result,
                            'outcome_uncertain': not verified}
                ready = admitted(ready_effect, ('git.publish',))
                results.append(ready)
                if not ready['ok']:
                    return {'ok': False, 'status': 'provider_result_uncertain', 'outcome_uncertain': True,
                            'results': results, 'gate_receipts': gates, 'served_adoption_verified': False}

            def merge_effect():
                ready_for_effect(observe())
                result = after = None
                merge_oid = None
                try:
                    result = _run(root, ['gh', 'pr', 'merge', params['pr'], '--repo', repository,
                        '--squash', '--match-head-commit', expected_head], timeout_seconds=180)
                    after = observe()
                    identity(after, merged=True)
                    merge_oid = (after.get('mergeCommit') or {}).get('oid')
                    verified = after.get('state') == 'MERGED' and bool(re.fullmatch(r'[0-9a-f]{40,64}', str(merge_oid)))
                except Exception:
                    verified = False
                return {'ok': verified, 'stage': 'pr.merge', 'status': 'merged' if verified else 'provider_result_uncertain',
                        'outcome_uncertain': not verified, 'result': result,
                        'merge_commit': merge_oid if verified else None}
            merged = admitted(merge_effect, ('git.publish',))
            results.append(merged)
            return {**merged, 'head': expected_head, 'results': results, 'gate_receipts': gates,
                    'reviewer': review['reviewer'], 'served_adoption_verified': False}
        except Exception as exc:
            code = getattr(exc, 'code', str(exc) if isinstance(exc, ContributionError) else 'proposal_effect_failed')
            return {'ok': False, 'error_code': code, 'status': 'partial' if results else 'refused',
                    'results': results, 'gate_receipts': getattr(exc, 'details', {}).get('gate_receipts', gates), 'outcome_uncertain': False,
                    'served_adoption_verified': False}
