"""Fail-closed mutation boundary for canonical action lifecycle changes.

The read side remains deliberately permissive through
``wiki_core.action_state.resolve_action_state``: old ``state``/``status`` and
body ``State:`` lines can still be understood.  The write side in this module
is stricter:

* the requested target is an exact canonical ``action_state`` value;
* every state change follows ``ACTION_STATE_TRANSITIONS``;
* legacy sources are canonicalized once, without deleting the legacy field;
* terminal/blocking contract fields are present before the atomic write;
* a chained, content-bound transition receipt is appended to frontmatter;
* diagnostics never echo page contents, reasons, receipts or absolute paths.

The local operator endpoint ``/api/actions/transition`` is the first real
writer backed by this boundary. ``wiki_audit.py`` validates its receipt chain
against the PR base, so a hand edit or agent edit cannot silently bypass the
state machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

try:  # POSIX operator deployments (macOS/Linux) get cross-process locking.
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - expected on Windows.
    _fcntl = None

try:  # Windows uses the standard CRT byte-range lock on the same lock file.
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - expected on POSIX.
    _msvcrt = None

from wiki_core.action_state import (
    ACTION_STATE_TRANSITIONS,
    CANONICAL_ACTION_STATES,
    NON_TERMINAL_ACTION_STATES,
    legacy_action_state_from_body,
    resolve_action_state,
    valid_action_transition,
)
from wiki_core.detectors import scan_text
from wiki_core.frontmatter import FRONTMATTER_RE


ACTION_TRANSITION_RECEIPT_VERSION = "wiki_action_transition_receipt.v2"
_LEGACY_ACTION_TRANSITION_RECEIPT_VERSION = "wiki_action_transition_receipt.v1"
_RECEIPT_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_SUPPORT_FIELDS_V1 = (
    "next_action",
    "blocker_reason",
    "completion_receipt",
    "cancellation_receipt",
)
_SUPPORT_FIELDS = (
    "next_action",
    "blocked_by",
    "blocker_reason",
    "completed_at",
    "completion_receipt",
    "cancellation_receipt",
)
_V2_ONLY_SUPPORT_FIELDS = frozenset(set(_SUPPORT_FIELDS) - set(_SUPPORT_FIELDS_V1))
_IMMUTABLE_RECEIPT_FIELDS = frozenset({"completion_receipt", "cancellation_receipt"})
_IMMUTABLE_TERMINAL_FIELDS = frozenset(
    {"completed_at", "completion_receipt", "cancellation_receipt"}
)
_HISTORY_FIELD = "action_state_history"
_MAX_REASON_CHARS = 500
_MAX_SUPPORT_FIELD_CHARS = 2_000
_TRANSITION_LOCK = threading.RLock()
_LOCK_ROOT = Path("data/derived/action-transition-locks")


@dataclass
class ActionTransitionError(ValueError):
    """Safe structured refusal from the action mutation boundary."""

    code: str
    current_state: str = ""
    next_state: str = ""
    allowed_next_states: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"action transition refused ({self.code})"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": "action transition refused",
            "error_code": self.code,
        }
        if self.current_state:
            payload["current_state"] = self.current_state
        if self.next_state:
            payload["next_state"] = self.next_state
        if self.allowed_next_states:
            payload["allowed_next_states"] = list(self.allowed_next_states)
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class ActionTransitionReceipt:
    """Public-safe result of one transition attempt."""

    receipt_id: str
    page_id: str
    page_ref: str
    previous_state: str
    next_state: str
    state_source: str
    changed: bool
    idempotent: bool
    canonicalized_legacy: bool
    reason_recorded: bool
    before_sha256: str
    after_sha256: str
    recorded_at: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ACTION_TRANSITION_RECEIPT_VERSION,
            "ok": True,
            "receipt_id": self.receipt_id,
            "page_id": self.page_id,
            "page_ref": self.page_ref,
            "previous_state": self.previous_state,
            "next_state": self.next_state,
            "state_source": self.state_source,
            "changed": self.changed,
            "idempotent": self.idempotent,
            "canonicalized_legacy": self.canonicalized_legacy,
            "reason_recorded": self.reason_recorded,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "recorded_at": self.recorded_at,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ActionTransitionDiagnostic:
    """One safe audit finding for a changed action document."""

    code: str
    message: str


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _revision_sha256(text: str) -> str:
    """Git-readable revision hash insensitive only to terminal newlines.

    The audit helper reads the base blob through a command wrapper that strips
    terminal newlines.  This secondary hash binds the receipt to that base
    without weakening ``before_sha256``, which remains the exact file hash used
    by optimistic-concurrency callers.
    """

    return _sha256_text(text.rstrip("\r\n"))


def _receipt_id(entry: Mapping[str, Any]) -> str:
    canonical = {
        str(key): value for key, value in entry.items() if str(key) != "receipt_id"
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{_sha256_text(encoded)}"


def _parse_document(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if match is None:
        raise ActionTransitionError("missing_frontmatter")
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ActionTransitionError("invalid_frontmatter") from exc
    if not isinstance(loaded, dict):
        raise ActionTransitionError("invalid_frontmatter")
    return dict(loaded), text[match.end() :]


def _render_document(frontmatter: Mapping[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(
        dict(frontmatter),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{dumped}---\n{body}"


def _contained_action_path(root: Path, page: Path | str) -> tuple[Path, str]:
    root_resolved = Path(root).resolve()
    supplied = Path(page)
    candidate = supplied if supplied.is_absolute() else root_resolved / supplied
    lexical = Path(os.path.abspath(candidate))
    try:
        relative = lexical.relative_to(root_resolved)
    except ValueError as exc:
        raise ActionTransitionError("path_outside_repo") from exc
    if not relative.parts or lexical.suffix.lower() != ".md":
        raise ActionTransitionError("invalid_action_path")

    current = root_resolved
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ActionTransitionError("symlink_action_path")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ActionTransitionError("action_not_found") from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ActionTransitionError("path_outside_repo") from exc
    if not resolved.is_file():
        raise ActionTransitionError("action_not_found")
    return resolved, relative.as_posix()


def _contained_lock_directory(root: Path) -> Path:
    """Create the ignored lock directory without following a symlink escape."""

    root_resolved = Path(root).resolve()
    current = root_resolved
    for part in _LOCK_ROOT.parts:
        current /= part
        if current.is_symlink():
            raise ActionTransitionError("action_lock_symlink")
    try:
        current.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved = current.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise ActionTransitionError("action_lock_failed") from exc
    # Recheck every component after mkdir; this also catches a pre-existing
    # in-repo symlink whose resolved target happens to remain inside the repo.
    walk = root_resolved
    for part in _LOCK_ROOT.parts:
        walk /= part
        if walk.is_symlink():
            raise ActionTransitionError("action_lock_symlink")
    return resolved


@contextmanager
def _action_file_lock(root: Path, page_ref: str) -> Iterator[None]:
    """Serialize one action across operator processes with a path-hiding lock."""

    if _fcntl is None and _msvcrt is None:
        raise ActionTransitionError("action_lock_backend_unavailable")
    directory = _contained_lock_directory(root)
    lock_name = f"{_sha256_text(page_ref)}.lock"
    lock_path = directory / lock_name
    if lock_path.is_symlink():
        raise ActionTransitionError("action_lock_symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ActionTransitionError("action_lock_failed") from exc
    try:
        lock_state = os.fstat(descriptor)
        if not stat.S_ISREG(lock_state.st_mode):
            raise ActionTransitionError("action_lock_failed")
        if lock_state.st_nlink != 1:
            raise ActionTransitionError("action_lock_hardlink")
        if _fcntl is not None:
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX)
            except OSError as exc:
                raise ActionTransitionError("action_lock_failed") from exc
        elif _msvcrt is not None:  # pragma: no cover - exercised on Windows CI.
            try:
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                _msvcrt.locking(descriptor, _msvcrt.LK_LOCK, 1)
            except OSError as exc:
                raise ActionTransitionError("action_lock_failed") from exc
        yield
    finally:
        if _fcntl is not None:
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
            except OSError:
                pass
        elif _msvcrt is not None:  # pragma: no cover - exercised on Windows CI.
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(descriptor)


def _safe_text(value: Any, *, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ActionTransitionError(f"{field}_too_long")
    return text


def _assert_no_secrets(text: str) -> None:
    if any(finding.category == "secret" for finding in scan_text(text)):
        raise ActionTransitionError("secret_blocked")


def _history(frontmatter: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = frontmatter.get(_HISTORY_FIELD)
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ActionTransitionError("invalid_action_state_history")
    return [dict(item) for item in raw]


def _last_receipt_id(history: list[dict[str, Any]]) -> str:
    for entry in reversed(history):
        receipt_id = str(entry.get("receipt_id") or "")
        if _RECEIPT_ID_RE.fullmatch(receipt_id):
            return receipt_id
    return ""


def _governed_support_value(frontmatter: Mapping[str, Any], field: str) -> Any:
    value = frontmatter.get(field)
    if field == "blocked_by":
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return str(value or "").strip()


def _support_fields_for_version(schema_version: str) -> tuple[str, ...]:
    if schema_version == _LEGACY_ACTION_TRANSITION_RECEIPT_VERSION:
        return _SUPPORT_FIELDS_V1
    return _SUPPORT_FIELDS


def _governed_support(
    frontmatter: Mapping[str, Any],
    *,
    schema_version: str = ACTION_TRANSITION_RECEIPT_VERSION,
) -> dict[str, Any]:
    return {
        field: _governed_support_value(frontmatter, field)
        for field in _support_fields_for_version(schema_version)
    }


def _governed_support_sha256(
    frontmatter: Mapping[str, Any],
    *,
    schema_version: str = ACTION_TRANSITION_RECEIPT_VERSION,
) -> str:
    return _sha256_text(
        json.dumps(
            _governed_support(frontmatter, schema_version=schema_version),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _lifecycle_contract_error(frontmatter: Mapping[str, Any], state: str) -> str:
    """Return one safe code when lifecycle fields contradict canonical state."""

    next_action = str(frontmatter.get("next_action") or "").strip()
    blocker_reason = str(frontmatter.get("blocker_reason") or "").strip()
    raw_blocked_by = frontmatter.get("blocked_by")
    if raw_blocked_by not in (None, []) and not isinstance(raw_blocked_by, list):
        return "invalid_blocked_by"
    blocked_by = [
        str(item).strip()
        for item in (raw_blocked_by if isinstance(raw_blocked_by, list) else [])
        if str(item).strip()
    ]
    completed_at = str(frontmatter.get("completed_at") or "").strip()
    completion_receipt = str(frontmatter.get("completion_receipt") or "").strip()
    cancellation_receipt = str(frontmatter.get("cancellation_receipt") or "").strip()

    if (
        state in NON_TERMINAL_ACTION_STATES
        and not next_action
    ):
        return "missing_next_action"
    if state in {"done", "cancelled"} and next_action:
        return "next_action_not_allowed"
    if state == "blocked" and not blocker_reason:
        return "missing_blocker_reason"
    if state != "blocked" and blocker_reason:
        return "blocker_reason_not_allowed"
    if state != "blocked" and blocked_by:
        return "blocked_by_not_allowed"
    if state == "done" and not completion_receipt:
        return "missing_completion_receipt"
    if state != "done" and completion_receipt:
        return "completion_receipt_not_allowed"
    if state == "cancelled" and not cancellation_receipt:
        return "missing_cancellation_receipt"
    if state != "cancelled" and cancellation_receipt:
        return "cancellation_receipt_not_allowed"
    if state in {"done", "cancelled"} and not completed_at:
        return "missing_completed_at"
    if state in NON_TERMINAL_ACTION_STATES and completed_at:
        return "completed_at_not_allowed"
    return ""


def _safe_blocked_by(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ActionTransitionError("blocked_by_must_be_list")
    if len(value) > 128:
        raise ActionTransitionError("blocked_by_too_many")
    output: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ActionTransitionError("blocked_by_invalid_ref")
        ref = _safe_text(raw, field="blocked_by_ref", limit=_MAX_SUPPORT_FIELD_CHARS)
        if ref not in output:
            output.append(ref)
    return output


def _transition_instant(recorded_at: str | None) -> tuple[str, datetime]:
    value = recorded_at or datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    if not _INSTANT_RE.fullmatch(value):
        raise ActionTransitionError("invalid_recorded_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActionTransitionError("invalid_recorded_at") from exc
    if parsed.tzinfo is None:
        raise ActionTransitionError("invalid_recorded_at")
    return value, parsed


def _parsed_transition_instant(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not _INSTANT_RE.fullmatch(raw):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _history_last_instant(history: list[dict[str, Any]]) -> datetime | None:
    previous: datetime | None = None
    for entry in history:
        schema_version = str(entry.get("schema_version") or "")
        if schema_version not in {
            _LEGACY_ACTION_TRANSITION_RECEIPT_VERSION,
            ACTION_TRANSITION_RECEIPT_VERSION,
        }:
            raise ActionTransitionError("invalid_action_state_history")
        current = _parsed_transition_instant(entry.get("at"))
        if current is None:
            raise ActionTransitionError("invalid_action_state_history")
        if previous is not None and (
            current < previous
            or (
                schema_version == ACTION_TRANSITION_RECEIPT_VERSION
                and current == previous
            )
        ):
            raise ActionTransitionError("non_monotonic_action_history")
        previous = current
    return previous


def _frontmatter_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _atomic_write(path: Path, text: str) -> bool:
    """Replace one file atomically; return whether its directory was fsynced."""

    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise ActionTransitionError("action_write_failed") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    if os.name == "nt":
        # Python/Windows has no portable directory-fsync primitive. The file
        # itself was flushed and os.replace is atomic, but the receipt reports
        # the narrower crash-durability guarantee.
        return False
    directory_fd: int | None = None
    try:
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        # The temp file was fsynced before replace; syncing the containing
        # directory makes the atomic rename durable across a crash.
        os.fsync(directory_fd)
    except OSError:
        # The atomic replace has already committed. Report the narrower
        # durability guarantee on the successful receipt; never return a
        # refusal that falsely implies rollback and invites a stale reattempt.
        return False
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    return True


def _transition_action_page_locked(
    root: Path,
    page: Path | str,
    next_state: str,
    *,
    reason: str | None = None,
    next_action: str | None = None,
    blocked_by: list[str] | tuple[str, ...] | None = None,
    blocker_reason: str | None = None,
    completion_receipt: str | None = None,
    cancellation_receipt: str | None = None,
    expected_sha256: str | None = None,
    recorded_at: str | None = None,
) -> ActionTransitionReceipt:
    """Apply one canonical action transition and return a safe receipt.

    ``expected_sha256`` is required by the operator adapter and optional for a
    trusted in-process caller. The caller supplies only state-contract fields;
    this is not a generic frontmatter patch API.
    """

    target = str(next_state or "").strip()
    if target not in CANONICAL_ACTION_STATES:
        raise ActionTransitionError("invalid_target_state", next_state=target)
    path, page_ref = _contained_action_path(root, page)
    try:
        before_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ActionTransitionError("action_read_failed") from exc
    before_sha256 = _sha256_text(before_text)
    expected = str(expected_sha256 or "").strip()
    if expected:
        if not _SHA256_RE.fullmatch(expected):
            raise ActionTransitionError("invalid_expected_sha256")
        if expected != before_sha256:
            raise ActionTransitionError("stale_action_revision")

    frontmatter, body = _parse_document(before_text)
    if str(frontmatter.get("page_type") or "").strip() != "action":
        raise ActionTransitionError("page_type_not_action")
    page_id = str(frontmatter.get("page_id") or "").strip()
    if not page_id:
        raise ActionTransitionError("missing_page_id")

    resolution = resolve_action_state(
        frontmatter,
        legacy_state=legacy_action_state_from_body(body),
    )
    if not resolution.valid:
        raise ActionTransitionError(
            "invalid_current_state",
            next_state=target,
            warnings=resolution.warnings,
        )
    current = resolution.state
    allowed = tuple(sorted(ACTION_STATE_TRANSITIONS.get(current, frozenset())))
    if not valid_action_transition(current, target):
        raise ActionTransitionError(
            "invalid_transition",
            current_state=current,
            next_state=target,
            allowed_next_states=allowed,
            warnings=resolution.warnings,
        )

    reason_text = _safe_text(reason, field="reason", limit=_MAX_REASON_CHARS)
    supplied: dict[str, Any] = {}
    for field, value in (
        ("next_action", next_action),
        ("blocker_reason", blocker_reason),
        ("completion_receipt", completion_receipt),
        ("cancellation_receipt", cancellation_receipt),
    ):
        if value is not None:
            supplied[field] = _safe_text(
                value,
                field=field,
                limit=_MAX_SUPPORT_FIELD_CHARS,
            )
    if blocked_by is not None:
        supplied["blocked_by"] = _safe_blocked_by(blocked_by)
    for field, required_state in (
        ("blocked_by", "blocked"),
        ("blocker_reason", "blocked"),
        ("completion_receipt", "done"),
        ("cancellation_receipt", "cancelled"),
    ):
        if field in supplied and target != required_state:
            raise ActionTransitionError(
                f"{field}_not_allowed",
                current_state=current,
                next_state=target,
            )
    _assert_no_secrets(
        yaml.safe_dump(
            {"reason": reason_text, **supplied},
            sort_keys=True,
            allow_unicode=True,
        )
    )
    at, parsed_at = _transition_instant(recorded_at)

    updated = dict(frontmatter)
    for field, value in supplied.items():
        existing = _governed_support_value(updated, field)
        if field in _IMMUTABLE_RECEIPT_FIELDS and existing and existing != value:
            raise ActionTransitionError(
                "immutable_receipt_conflict",
                current_state=current,
                next_state=target,
            )
        updated[field] = value
    updated["action_state"] = target
    if target in {"done", "cancelled"}:
        # Terminal states are historical facts, not still-actionable work.
        # Bind the terminal instant to the same clock used by the receipt and
        # remove every field owned by a different lifecycle state.
        if current != target or not str(updated.get("completed_at") or "").strip():
            updated["completed_at"] = at
        updated.pop("next_action", None)
        updated.pop("blocker_reason", None)
        updated.pop("blocked_by", None)
        opposite_receipt = (
            "cancellation_receipt" if target == "done" else "completion_receipt"
        )
        updated.pop(opposite_receipt, None)
    else:
        updated.pop("completed_at", None)
        updated.pop("completion_receipt", None)
        updated.pop("cancellation_receipt", None)
        if target != "blocked":
            # A prior blocker describes the old state and must not leak into
            # the newly actionable contract. Both blocker fields are governed
            # so the transition receipt proves their removal.
            updated.pop("blocker_reason", None)
            updated.pop("blocked_by", None)

    contract_error = _lifecycle_contract_error(updated, target)
    if contract_error:
        raise ActionTransitionError(
            contract_error,
            current_state=current,
            next_state=target,
        )

    history = _history(frontmatter)
    last_history_instant = _history_last_instant(history)
    canonicalized_legacy = resolution.source != "action_state"
    state_changed = current != target or canonicalized_legacy
    support_fields = sorted(
        field
        for field in _SUPPORT_FIELDS
        if _governed_support_value(frontmatter, field)
        != _governed_support_value(updated, field)
    )
    support_changed = bool(support_fields)
    changed = state_changed or support_changed

    if changed:
        if last_history_instant is not None and parsed_at <= last_history_instant:
            raise ActionTransitionError(
                "non_monotonic_recorded_at",
                current_state=current,
                next_state=target,
            )
        prior_updated_at = _frontmatter_date(frontmatter.get("updated_at"))
        transition_date = parsed_at.astimezone(timezone.utc).date()
        if prior_updated_at is not None and transition_date < prior_updated_at:
            raise ActionTransitionError(
                "recorded_at_before_updated_at",
                current_state=current,
                next_state=target,
            )

    if not changed:
        if reason_text:
            raise ActionTransitionError(
                "reason_without_change",
                current_state=current,
                next_state=target,
            )
        _assert_no_secrets(before_text)
        prior_id = _last_receipt_id(history)
        if not prior_id:
            prior_id = _receipt_id(
                {
                    "schema_version": ACTION_TRANSITION_RECEIPT_VERSION,
                    "kind": "idempotent_noop",
                    "page_id": page_id,
                    "from": current,
                    "to": target,
                    "before_sha256": before_sha256,
                }
            )
        recorded = ""
        if history:
            recorded = str(history[-1].get("at") or "")
        return ActionTransitionReceipt(
            receipt_id=prior_id,
            page_id=page_id,
            page_ref=page_ref,
            previous_state=current,
            next_state=target,
            state_source=resolution.source,
            changed=False,
            idempotent=True,
            canonicalized_legacy=False,
            reason_recorded=False,
            before_sha256=before_sha256,
            after_sha256=before_sha256,
            recorded_at=recorded,
            warnings=resolution.warnings,
        )

    if current != target:
        kind = "transition"
    elif canonicalized_legacy:
        kind = "legacy_canonicalization"
    else:
        kind = "contract_update"
    support_payload = {
        field: _governed_support_value(updated, field) for field in support_fields
    }
    payload_sha256 = _sha256_text(
        json.dumps(
            {"reason": reason_text, "support": support_payload},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    entry: dict[str, Any] = {
        "schema_version": ACTION_TRANSITION_RECEIPT_VERSION,
        "kind": kind,
        "page_id": page_id,
        "from": current,
        "to": target,
        "at": at,
        "state_source": resolution.source,
        "before_sha256": before_sha256,
        "before_revision": _revision_sha256(before_text),
        "payload_sha256": payload_sha256,
        "support_fields": support_fields,
        "governed_support_sha256": _governed_support_sha256(updated),
        "prior_receipt_id": _last_receipt_id(history),
        "reason_recorded": bool(reason_text),
    }
    entry["receipt_id"] = _receipt_id(entry)
    if reason_text:
        entry["reason"] = reason_text
        # The receipt id intentionally covers the actual recorded reason.
        entry["receipt_id"] = _receipt_id(entry)
    history.append(entry)
    updated[_HISTORY_FIELD] = history
    updated["updated_at"] = parsed_at.astimezone(timezone.utc).date().isoformat()
    after_text = _render_document(updated, body)
    _assert_no_secrets(after_text)
    directory_synced = _atomic_write(path, after_text)
    after_sha256 = _sha256_text(after_text)

    warnings = list(resolution.warnings)
    if canonicalized_legacy:
        warnings.append("legacy_action_state_canonicalized")
    if not directory_synced:
        warnings.append("directory_fsync_unavailable")
    return ActionTransitionReceipt(
        receipt_id=str(entry["receipt_id"]),
        page_id=page_id,
        page_ref=page_ref,
        previous_state=current,
        next_state=target,
        state_source=resolution.source,
        changed=True,
        idempotent=False,
        canonicalized_legacy=canonicalized_legacy,
        reason_recorded=bool(reason_text),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        recorded_at=at,
        warnings=tuple(warnings),
    )


def transition_action_page(
    root: Path,
    page: Path | str,
    next_state: str,
    *,
    reason: str | None = None,
    next_action: str | None = None,
    blocked_by: list[str] | tuple[str, ...] | None = None,
    blocker_reason: str | None = None,
    completion_receipt: str | None = None,
    cancellation_receipt: str | None = None,
    expected_sha256: str | None = None,
    recorded_at: str | None = None,
) -> ActionTransitionReceipt:
    """Serialize the full read/check/write transaction by action and process."""

    if os.name == "nt":
        raise ActionTransitionError("action_writes_unsupported_on_windows")
    resolved_page, page_ref = _contained_action_path(root, page)
    with _TRANSITION_LOCK:
        with _action_file_lock(root, page_ref):
            return _transition_action_page_locked(
                root,
                resolved_page,
                next_state,
                reason=reason,
                next_action=next_action,
                blocked_by=blocked_by,
                blocker_reason=blocker_reason,
                completion_receipt=completion_receipt,
                cancellation_receipt=cancellation_receipt,
                expected_sha256=expected_sha256,
                recorded_at=recorded_at,
            )


def _document_for_audit(text: str) -> tuple[dict[str, Any], str] | None:
    try:
        return _parse_document(text)
    except ActionTransitionError:
        return None


def _receipt_entry_error(
    entry: Mapping[str, Any],
    *,
    expected_from: str,
    expected_page_id: str,
    expected_prior_receipt_id: str,
    expected_first_revision: str | None,
    expected_prior_at: datetime | None,
) -> str:
    schema_version = str(entry.get("schema_version") or "")
    if schema_version not in {
        _LEGACY_ACTION_TRANSITION_RECEIPT_VERSION,
        ACTION_TRANSITION_RECEIPT_VERSION,
    }:
        return "receipt schema is missing or unsupported"
    if str(entry.get("page_id") or "") != expected_page_id:
        return "receipt page_id does not match the audited action"
    receipt_id = str(entry.get("receipt_id") or "")
    if not _RECEIPT_ID_RE.fullmatch(receipt_id) or receipt_id != _receipt_id(entry):
        return "receipt id is missing or does not match its safe payload"
    if str(entry.get("prior_receipt_id") or "") != expected_prior_receipt_id:
        return "receipt chain does not extend the prior action history"
    previous = str(entry.get("from") or "")
    target = str(entry.get("to") or "")
    if previous != expected_from:
        return "receipt chain starts from a state different from the prior action"
    kind = str(entry.get("kind") or "")
    if previous == target:
        if kind not in {"legacy_canonicalization", "contract_update"}:
            return "state-preserving receipt has an invalid kind"
    else:
        if not valid_action_transition(previous, target):
            return f"receipt contains invalid transition `{previous}` -> `{target}`"
        if kind != "transition":
            return "state-changing receipt must have kind `transition`"
    if str(entry.get("state_source") or "") not in {
        "action_state",
        "state",
        "status",
        "body_state",
        "default",
    }:
        return "receipt has an invalid prior-state source"
    parsed_at = _parsed_transition_instant(entry.get("at"))
    if parsed_at is None:
        return "receipt has an invalid timestamp"
    if expected_prior_at is not None and (
        parsed_at < expected_prior_at
        or (
            schema_version == ACTION_TRANSITION_RECEIPT_VERSION
            and parsed_at == expected_prior_at
        )
    ):
        return "receipt timestamps are not causally monotonic"
    reason_recorded = entry.get("reason_recorded")
    if not isinstance(reason_recorded, bool):
        return "receipt reason_recorded flag must be boolean"
    if reason_recorded != bool(str(entry.get("reason") or "").strip()):
        return "receipt reason flag does not match the recorded reason"
    if not _SHA256_RE.fullmatch(str(entry.get("before_sha256") or "")):
        return "receipt is missing its exact pre-write hash"
    if not _SHA256_RE.fullmatch(str(entry.get("before_revision") or "")):
        return "receipt is missing its base-comparable revision hash"
    if (
        expected_first_revision is not None
        and str(entry.get("before_revision") or "") != expected_first_revision
    ):
        return "first receipt is not bound to the audited base action"
    if not _SHA256_RE.fullmatch(str(entry.get("payload_sha256") or "")):
        return "receipt is missing its redacted payload hash"
    support_fields = entry.get("support_fields")
    allowed_support_fields = _support_fields_for_version(schema_version)
    if (
        not isinstance(support_fields, list)
        or any(field not in allowed_support_fields for field in support_fields)
        or support_fields != sorted(set(support_fields))
    ):
        return "receipt governed support fields are invalid"
    if kind == "contract_update" and not support_fields:
        return "contract-update receipt must bind at least one governed support field"
    if not _SHA256_RE.fullmatch(str(entry.get("governed_support_sha256") or "")):
        return "receipt is missing its governed support hash"
    return ""


def action_transition_diagnostics(
    previous_text: str,
    current_text: str,
) -> tuple[ActionTransitionDiagnostic, ...]:
    """Validate the receipt chain for an action changed from a Git base.

    New action creation is validated by the page-type gate, not treated as a
    transition.  This function handles an existing action whose authored
    lifecycle or receipt history changed.
    """

    previous_document = _document_for_audit(previous_text)
    current_document = _document_for_audit(current_text)
    if previous_document is None or current_document is None:
        return ()
    previous, previous_body = previous_document
    current, current_body = current_document
    previous_type = str(previous.get("page_type") or "")
    current_type = str(current.get("page_type") or "")
    if previous_type != "action" and current_type != "action":
        return ()
    if previous_type == "action" and current_type != "action":
        return (
            ActionTransitionDiagnostic(
                "action_page_type_changed",
                "an existing action cannot bypass its lifecycle by changing page_type",
            ),
        )
    if previous_type != "action":
        return ()

    previous_page_id = str(previous.get("page_id") or "").strip()
    current_page_id = str(current.get("page_id") or "").strip()
    if not previous_page_id or current_page_id != previous_page_id:
        return (
            ActionTransitionDiagnostic(
                "action_page_id_changed",
                "an existing action cannot change its immutable page_id",
            ),
        )

    previous_resolution = resolve_action_state(
        previous,
        legacy_state=legacy_action_state_from_body(previous_body),
    )
    current_resolution = resolve_action_state(
        current,
        legacy_state=legacy_action_state_from_body(current_body),
    )
    if not previous_resolution.valid:
        return (
            ActionTransitionDiagnostic(
                "invalid_base_action_state",
                "the audited base action has an invalid canonical lifecycle state",
            ),
        )
    if not current_resolution.valid or current_resolution.source != "action_state":
        return (
            ActionTransitionDiagnostic(
                "invalid_current_action_state",
                "a changed action must author one exact canonical action_state",
            ),
        )

    previous_history_raw = previous.get(_HISTORY_FIELD)
    current_history_raw = current.get(_HISTORY_FIELD)
    previous_history = (
        [] if previous_history_raw in (None, []) else previous_history_raw
    )
    current_history = [] if current_history_raw in (None, []) else current_history_raw
    if not isinstance(previous_history, list) or any(
        not isinstance(item, dict) for item in previous_history
    ):
        return (
            ActionTransitionDiagnostic(
                "invalid_base_action_history",
                "the audited base action has malformed action_state_history",
            ),
        )
    if not isinstance(current_history, list) or any(
        not isinstance(item, dict) for item in current_history
    ):
        return (
            ActionTransitionDiagnostic(
                "invalid_current_action_history",
                "the changed action has malformed action_state_history",
            ),
        )
    if current_history[: len(previous_history)] != previous_history:
        return (
            ActionTransitionDiagnostic(
                "action_history_rewritten",
                "action_state_history is append-only and cannot rewrite its audited base",
            ),
        )

    try:
        expected_prior_at = _history_last_instant(
            [dict(item) for item in previous_history]
        )
    except ActionTransitionError:
        return (
            ActionTransitionDiagnostic(
                "invalid_base_action_history",
                "the audited base action has non-monotonic or malformed receipt time",
            ),
        )

    for field in _IMMUTABLE_TERMINAL_FIELDS:
        prior_value = str(previous.get(field) or "").strip()
        current_value = str(current.get(field) or "").strip()
        field_owned_by_prior_state = (
            field == "completed_at"
            or (field == "completion_receipt" and previous_resolution.state == "done")
            or (
                field == "cancellation_receipt"
                and previous_resolution.state == "cancelled"
            )
        )
        if (
            previous_resolution.state in {"done", "cancelled"}
            and field_owned_by_prior_state
            and prior_value
            and current_value != prior_value
        ):
            return (
                ActionTransitionDiagnostic(
                    "terminal_action_receipt_rewritten",
                    "an authored terminal fact is immutable and cannot be rewritten",
                ),
            )

    current_contract_error = _lifecycle_contract_error(
        current, current_resolution.state
    )
    if current_contract_error:
        return (
            ActionTransitionDiagnostic(
                "invalid_action_lifecycle_contract",
                "the changed action has state-incompatible lifecycle fields "
                f"({current_contract_error})",
            ),
        )

    additions = current_history[len(previous_history) :]
    # Adopting ``action_state: open`` over an equivalent legacy ``status: open``
    # is schema migration, not a lifecycle edge.  The central writer receipts
    # that canonicalization when used, but the PR gate must not block existing
    # migration/generator paths that preserve the exact semantic state.
    lifecycle_changed = previous_resolution.state != current_resolution.state
    support_changed = _governed_support(previous) != _governed_support(current)
    if (lifecycle_changed or support_changed) and not additions:
        message = (
            "action_state changed without a transition receipt"
            if lifecycle_changed
            else "governed action support changed without a transition receipt"
        )
        return (
            ActionTransitionDiagnostic(
                "missing_action_transition_receipt",
                message,
            ),
        )
    if not additions:
        return ()

    expected_state = previous_resolution.state
    prior_receipt_id = _last_receipt_id(
        [dict(item) for item in previous_history if isinstance(item, dict)]
    )
    first_revision: str | None = _revision_sha256(previous_text)
    terminal_transition_at = ""
    for raw_entry in additions:
        entry = dict(raw_entry)
        error = _receipt_entry_error(
            entry,
            expected_from=expected_state,
            expected_page_id=current_page_id,
            expected_prior_receipt_id=prior_receipt_id,
            expected_first_revision=first_revision,
            expected_prior_at=expected_prior_at,
        )
        if error:
            return (
                ActionTransitionDiagnostic("invalid_action_transition_receipt", error),
            )
        expected_state = str(entry.get("to") or "")
        entry_at = _parsed_transition_instant(entry.get("at"))
        assert entry_at is not None  # validated by _receipt_entry_error
        expected_prior_at = entry_at
        if (
            expected_state in {"done", "cancelled"}
            and (
                str(entry.get("from") or "") != expected_state
                or "completed_at" in (entry.get("support_fields") or [])
            )
        ):
            terminal_transition_at = str(entry.get("at") or "")
        prior_receipt_id = str(entry.get("receipt_id") or "")
        first_revision = None
    if expected_state != current_resolution.state:
        return (
            ActionTransitionDiagnostic(
                "action_transition_receipt_state_mismatch",
                "transition receipt chain does not end at the authored action_state",
            ),
        )
    previous_updated_at = _frontmatter_date(previous.get("updated_at"))
    current_updated_at = _frontmatter_date(current.get("updated_at"))
    if (
        previous_updated_at is not None
        and current_updated_at is not None
        and current_updated_at < previous_updated_at
    ):
        return (
            ActionTransitionDiagnostic(
                "action_updated_at_regressed",
                "action updated_at regressed across an audited lifecycle change",
            ),
        )
    if additions and expected_prior_at is not None:
        receipt_date = expected_prior_at.astimezone(timezone.utc).date()
        if current_updated_at != receipt_date:
            return (
                ActionTransitionDiagnostic(
                    "action_transition_timestamp_mismatch",
                    "action updated_at does not match the latest transition receipt date",
                ),
            )
    if terminal_transition_at and str(current.get("completed_at") or "").strip() != (
        terminal_transition_at
    ):
        return (
            ActionTransitionDiagnostic(
                "action_terminal_timestamp_mismatch",
                "terminal completed_at does not match its transition receipt instant",
            ),
        )
    last_schema_version = str(additions[-1].get("schema_version") or "")
    if last_schema_version == _LEGACY_ACTION_TRANSITION_RECEIPT_VERSION and any(
        _governed_support_value(previous, field)
        != _governed_support_value(current, field)
        for field in _V2_ONLY_SUPPORT_FIELDS
    ):
        return (
            ActionTransitionDiagnostic(
                "action_transition_receipt_support_mismatch",
                "a legacy receipt cannot bind fields introduced by the current action contract",
            ),
        )
    if str(additions[-1].get("governed_support_sha256") or "") != (
        _governed_support_sha256(
            current,
            schema_version=last_schema_version,
        )
    ):
        return (
            ActionTransitionDiagnostic(
                "action_transition_receipt_support_mismatch",
                "transition receipt chain does not bind the authored governed support fields",
            ),
        )
    return ()


__all__ = [
    "ACTION_TRANSITION_RECEIPT_VERSION",
    "ActionTransitionDiagnostic",
    "ActionTransitionError",
    "ActionTransitionReceipt",
    "action_transition_diagnostics",
    "transition_action_page",
]
