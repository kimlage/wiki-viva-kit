"""Finite, host-bound failure routing primitives.

This module is not a scheduler, a GitHub client, or an authorization boundary.
A trusted host must supply fixed provider/worker ports and revalidate authority
for each effect. Nothing here grants access, launches a service, or establishes
that an adapter is installed. Synthetic adapters belong only in tests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Callable, Protocol

from wiki_core.action_transition import _action_file_lock
from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths
from wiki_core.repo_read import contains_access_secrets

_SAFE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}\Z")
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}\Z")
_STATES = frozenset({"queued", "running", "succeeded", "failed"})


class RoutingError(ValueError):
    """Closed error, without provider output or user data."""


class AdmissionDenied(Exception):
    """A trusted admission layer refused an effect before invoking it."""


@dataclass(frozen=True)
class FailureIntent:
    # All values are configured by the trusted host, not by issue text or HTTP.
    # key is stable and private; only a random marker leaves the host.
    key: str
    template: str
    issue_target: str
    executor: str
    adopter: str
    existing_issue: str | None = None

    def validate(self) -> None:
        if not all((v is None and k == "existing_issue") or
                   (isinstance(v, str) and _SAFE.fullmatch(v) and not contains_access_secrets(v))
                   for k, v in asdict(self).items()):
            raise RoutingError("invalid_intent")


@dataclass(frozen=True)
class IssueRef:
    identifier: str
    marker: str


@dataclass(frozen=True)
class RunRef:
    identifier: str
    key: str
    state: str


@dataclass(frozen=True)
class UpstreamMerge:
    revision: str
    merged: bool
    reviewed: bool
    ci_passed: bool


class IssuePort(Protocol):
    def find(self, target: str, marker: str) -> list[IssueRef]: ...
    def get(self, target: str, issue: str) -> IssueRef | None: ...
    def create(self, target: str, template: str, marker: str) -> None: ...
    def verified_merge(self, target: str, issue: str) -> UpstreamMerge | None: ...


class ExecutorPort(Protocol):
    def find(self, executor: str, key: str) -> list[RunRef]: ...
    def start(self, executor: str, key: str, issue: str, revision: str | None) -> None: ...


# The host must implement an effect-specific live authorization check, execute
# the supplied fixed internal function only when admitted, and raise
# AdmissionDenied before invoking it if refused. Never expose this callable to
# an untrusted request. Exceptions after invocation are treated as uncertain.
Admission = Callable[[str, Callable[[], Any]], Any]


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _directory(root: Path, config: WikiConfig) -> Path:
    root = Path(root).resolve(strict=True)
    if not isinstance(config, WikiConfig):
        raise RoutingError("config_invalid")
    try:
        relative = (WikiPaths(root, config).derived_root / "failure-routing").relative_to(root)
    except (ValueError, TypeError, KeyError):
        raise RoutingError("receipt_path_invalid") from None
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise RoutingError("receipt_path_invalid")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RoutingError("receipt_path_invalid")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
            if not current.is_dir() or current.resolve(strict=True) != current:
                raise RoutingError("receipt_path_invalid")
        except OSError:
            raise RoutingError("receipt_path_invalid") from None
    return current


def _read(path: Path) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise RoutingError("receipt_invalid")
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise RoutingError("receipt_invalid")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise RoutingError("receipt_invalid")
        return result
    except (OSError, ValueError, TypeError):
        raise RoutingError("receipt_invalid") from None


def _write(path: Path, record: dict[str, Any]) -> None:
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > 16384:
        raise RoutingError("receipt_invalid")
    if os.path.lexists(path):
        _read(path)  # Refuse symlinks, hardlinks and invalid files before replace.
    temp = path.with_name("." + path.name + "." + secrets.token_hex(8))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise RoutingError("receipt_write_failed") from None
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _one(values: Any, cls: type, key_name: str, key: str) -> Any:
    if not isinstance(values, list) or len(values) > 1:
        raise RoutingError("provider_conflict")
    if not values:
        return None
    item = values[0]
    if (not isinstance(item, cls) or getattr(item, key_name) != key
            or not isinstance(item.identifier, str) or not _SAFE.fullmatch(item.identifier)
            or contains_access_secrets(item.identifier)):
        raise RoutingError("provider_invalid")
    if isinstance(item, RunRef) and item.state not in _STATES:
        raise RoutingError("provider_invalid")
    return item


def _observe(admit: Admission, capability: str, call: Callable[[], Any]) -> Any:
    try:
        return admit(capability, call)
    except AdmissionDenied:
        raise RoutingError("admission_denied") from None
    except Exception:
        raise RoutingError("provider_unavailable") from None


def _attempt(admit: Admission, capability: str, call: Callable[[], Any]) -> str | None:
    try:
        admit(capability, call)
        return None
    except AdmissionDenied:
        return "admission_denied"
    except Exception:
        # The provider may have accepted the effect before timing out.
        return "outcome_uncertain"


def _intent_record(root: Path, intent: FailureIntent, config: WikiConfig) -> tuple[Path, dict[str, Any]]:
    identity = _digest(intent.key)
    path = _directory(root, config) / (identity + ".json")
    record = _read(path)
    digest = _digest(asdict(intent))
    if record is None:
        record = {"schema": "wiki.failure-route.v1", "intent_digest": digest,
                  "marker": secrets.token_hex(16), "issue_attempted": False,
                  "issue": None, "repair_attempted": False, "adoption_attempted": False,
                  "repair_run": None, "adoption_run": None, "adoption_revision": None}
        _write(path, record)
    if (set(record) != {"schema", "intent_digest", "marker", "issue_attempted", "issue",
                        "repair_attempted", "adoption_attempted", "repair_run", "adoption_run", "adoption_revision"}
            or record.get("schema") != "wiki.failure-route.v1" or record.get("intent_digest") != digest
            or not isinstance(record.get("marker"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", record["marker"])
            or any(type(record.get(k)) is not bool for k in ("issue_attempted", "repair_attempted", "adoption_attempted"))
            or any(record.get(k) is not None and (not isinstance(record[k], str) or not _SAFE.fullmatch(record[k]))
                   for k in ("issue", "repair_run", "adoption_run"))
            or (record.get("adoption_revision") is not None and
                (not isinstance(record["adoption_revision"], str) or not _SHA.fullmatch(record["adoption_revision"])) )):
        raise RoutingError("receipt_conflict")
    if ((record["issue"] is not None and not record["issue_attempted"] and intent.existing_issue is None)
            or (record["repair_run"] is not None and not record["repair_attempted"])
            or (record["adoption_run"] is not None and not record["adoption_attempted"])
            or (record["adoption_attempted"] and record["adoption_revision"] is None)
            or (record["issue"] is None and (record["repair_attempted"] or record["adoption_attempted"]
                                              or record["adoption_revision"] is not None))):
        raise RoutingError("receipt_conflict")
    return path, record


def _route_worker(path: Path, record: dict[str, Any], port: ExecutorPort | None,
                  admit: Admission, executor: str, phase: str, revision: str | None) -> dict[str, str]:
    if port is None:
        return {"state": "executor_unavailable"}
    if phase == "adoption":
        if record["adoption_revision"] is not None and record["adoption_revision"] != revision:
            raise RoutingError("revision_conflict")
        if record["adoption_revision"] is None:
            record["adoption_revision"] = revision
            _write(path, record)
    key = record["marker"] + "-" + phase
    def find() -> RunRef | None:
        return _one(_observe(admit, "executor.inspect", lambda: port.find(executor, key)), RunRef, "key", key)
    run = find()
    if run is None:
        field = phase + "_attempted"
        if record[field]:
            return {"state": "outcome_uncertain"}
        record[field] = True
        _write(path, record)  # Durable intent precedes effect.
        result = _attempt(admit, "executor.start", lambda: port.start(executor, key, record["issue"], revision))
        if result == "admission_denied":
            record[field] = False
            _write(path, record)
            return {"state": result}
        try:
            run = find()
        except RoutingError:
            return {"state": "outcome_uncertain"}
        if run is None:
            return {"state": "outcome_uncertain"}
    field = phase + "_run"
    if record[field] is not None and record[field] != run.identifier:
        raise RoutingError("provider_conflict")
    if record[field] is None:
        record[field] = run.identifier
        record[phase + "_attempted"] = True
        _write(path, record)
    return {"state": run.state, "run_id": run.identifier}


def route_failure(root: Path, intent: FailureIntent, *, issue_port: IssuePort,
                  executor_port: ExecutorPort | None, admit: Admission,
                  config: WikiConfig) -> dict[str, str]:
    """Process one failure once on one host; returned state is provider readback.

    Issue bodies are selected by the host-owned template, never by exception
    text. A provider timeout or a crash after intent persistence is reconciled
    by lookup; a missing/ambiguous observation never triggers a blind retry.
    """
    intent.validate()
    with _action_file_lock(Path(root), "failure-routing:" + _digest(intent.key)):
        path, record = _intent_record(Path(root), intent, config)
        marker = record["marker"]
        if intent.existing_issue is not None:
            existing = _observe(admit, "issue.inspect", lambda: issue_port.get(intent.issue_target, intent.existing_issue))
            if existing is None:
                return {"state": "issue_unconfirmed"}
            if not isinstance(existing, IssueRef) or existing.identifier != intent.existing_issue:
                raise RoutingError("provider_invalid")
            if record["issue"] not in (None, existing.identifier):
                raise RoutingError("provider_conflict")
            if record["issue"] is None:
                record["issue"] = existing.identifier
                _write(path, record)
            return {"issue_id": existing.identifier, **_route_worker(path, record, executor_port, admit, intent.executor, "repair", None)}
        def find() -> IssueRef | None:
            return _one(_observe(admit, "issue.inspect", lambda: issue_port.find(intent.issue_target, marker)), IssueRef, "marker", marker)
        issue = find()
        if issue is None:
            if record["issue"] is not None or record["issue_attempted"]:
                return {"state": "outcome_uncertain"}
            record["issue_attempted"] = True
            _write(path, record)
            result = _attempt(admit, "issue.create", lambda: issue_port.create(intent.issue_target, intent.template, marker))
            if result == "admission_denied":
                record["issue_attempted"] = False
                _write(path, record)
                return {"state": result}
            try:
                issue = find()
            except RoutingError:
                return {"state": "outcome_uncertain"}
            if issue is None:
                return {"state": "outcome_uncertain"}
        if record["issue"] is not None and record["issue"] != issue.identifier:
            raise RoutingError("provider_conflict")
        if record["issue"] is None:
            record["issue"] = issue.identifier
            record["issue_attempted"] = True
            _write(path, record)
        return {"issue_id": issue.identifier, **_route_worker(path, record, executor_port, admit, intent.executor, "repair", None)}


def route_adoption(root: Path, intent: FailureIntent, *, issue_port: IssuePort,
                   executor_port: ExecutorPort | None, admit: Admission,
                   config: WikiConfig) -> dict[str, str]:
    """Hand off adoption only after host-observed reviewed upstream merge.

    A queued or completed worker is not proof of integration. This function
    does not merge, change a lockfile, or assert the consumer has adopted it.
    """
    intent.validate()
    with _action_file_lock(Path(root), "failure-routing:" + _digest(intent.key)):
        path, record = _intent_record(Path(root), intent, config)
        if record["issue"] is None:
            return {"state": "issue_unconfirmed"}
        if intent.existing_issue is not None:
            observed = _observe(admit, "issue.inspect", lambda: issue_port.get(intent.issue_target, intent.existing_issue))
            if observed is not None and (not isinstance(observed, IssueRef) or observed.identifier != intent.existing_issue):
                raise RoutingError("provider_invalid")
        else:
            observed = _one(_observe(admit, "issue.inspect", lambda: issue_port.find(intent.issue_target, record["marker"])), IssueRef, "marker", record["marker"])
        if observed is None or observed.identifier != record["issue"]:
            return {"state": "issue_unconfirmed"}
        merge = _observe(admit, "upstream.inspect", lambda: issue_port.verified_merge(intent.issue_target, record["issue"]))
        if merge is None:
            return {"state": "upstream_not_merged"}
        if (not isinstance(merge, UpstreamMerge) or type(merge.merged) is not bool
                or type(merge.reviewed) is not bool or type(merge.ci_passed) is not bool
                or not isinstance(merge.revision, str) or not _SHA.fullmatch(merge.revision)):
            raise RoutingError("provider_invalid")
        if not (merge.merged and merge.reviewed and merge.ci_passed):
            return {"state": "upstream_not_ready"}
        return {"issue_id": record["issue"], "upstream_revision": merge.revision,
                **_route_worker(path, record, executor_port, admit, intent.adopter, "adoption", merge.revision)}
