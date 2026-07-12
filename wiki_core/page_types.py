from __future__ import annotations

import hashlib
import json
import re
import datetime as dt
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from wiki_core.action_state import (
    CANONICAL_ACTION_STATES,
    NON_TERMINAL_ACTION_STATES,
    resolve_action_state,
    valid_action_transition,
)
from wiki_core.config import load_config
from wiki_core.experience_packs import (
    PackError,
    load_lock,
    validate_installation,
    validate_manifest,
)
from wiki_core.frontmatter import FRONTMATTER_RE, parse_frontmatter

PAGE_TYPES_SCHEMA_VERSION = "wiki_page_types.v1"
PACK_PAGE_TYPES_SCHEMA_VERSION = "wiki_experience_pack_page_types.v1"

_PACK_PAGE_TYPE_FIELDS = {"title", "visibility", "template", "fields"}
_PACK_PRIVATE_VISIBILITIES = {"private", "private_self", "internal"}
_PACK_FIELD_RE = re.compile(r"[a-z][a-z0-9_]*")
_PACK_RESERVED_FIELDS = {
    "page_id",
    "page_type",
    "title",
    "context",
    "visibility",
    "updated_at",
    "stale_after_days",
    "template_id",
    "template_version",
    "template_ref",
    "template_overlay",
}
_ACTION_RECEIPT_SCHEMAS = {
    "wiki_action_transition_receipt.v1",
    "wiki_action_transition_receipt.v2",
}
_ACTION_SUPPORT_FIELDS_V1 = {
    "next_action",
    "blocker_reason",
    "completion_receipt",
    "cancellation_receipt",
}
_ACTION_SUPPORT_FIELDS_V2 = {
    *_ACTION_SUPPORT_FIELDS_V1,
    "blocked_by",
    "completed_at",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ACTION_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class PageTypeRegistry:
    path: Path
    schema_version: str
    page_types: dict[str, dict[str, Any]]


def load_page_type_registry(
    root: Path, path: str = "wiki.page-types.yaml"
) -> PageTypeRegistry | None:
    registry_path = root / path
    if not registry_path.exists():
        return None
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    page_types = data.get("page_types") or {}
    if not isinstance(page_types, dict):
        page_types = {}
    core_types = {str(k): v for k, v in page_types.items() if isinstance(v, dict)}
    memory_root = str(load_config(root).paths["memory_root"]).strip("/")
    pack_types = _load_active_pack_page_types(root, memory_root=memory_root)
    collisions = sorted(set(core_types) & set(pack_types))
    if collisions:
        raise PackError("page_type_conflict", collisions[0])
    return PageTypeRegistry(
        path=registry_path,
        schema_version=str(data.get("schema_version") or ""),
        page_types={**core_types, **pack_types},
    )


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_pack_relative(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PackError("unsafe_path", label)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackError("unsafe_path", label)
    return path.as_posix()


def _verified_pack_file(
    root: Path,
    pack_id: str,
    entry: dict[str, Any],
    relative: str,
) -> tuple[bytes, dict[str, Any]]:
    """Read one installed artifact only when it still matches the lock record."""

    relative = _safe_pack_relative(relative, label=f"pack artifact:{pack_id}")
    inventory = {
        str(record.get("path") or ""): record
        for record in entry.get("files") or []
        if isinstance(record, dict)
    }
    record = inventory.get(relative)
    if not isinstance(record, dict):
        raise PackError("installed_artifact_not_locked", f"{pack_id}:{relative}")
    base = root / str(entry["installed_path"])
    candidate = base / relative
    try:
        candidate.resolve(strict=False).relative_to(base.resolve())
    except ValueError as exc:
        raise PackError("unsafe_path", f"pack artifact:{pack_id}") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise PackError("installed_bundle_drift", pack_id)
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise PackError("installed_bundle_drift", pack_id) from exc
    if len(raw) != record.get("size") or hashlib.sha256(raw).hexdigest() != record.get(
        "sha256"
    ):
        raise PackError("installed_bundle_drift", pack_id)
    return raw, record


def _installed_manifest(
    root: Path,
    pack_id: str,
    entry: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    report = validate_installation(root, pack_id)
    if report.get("status") != "valid":
        codes = sorted(
            {
                str(row.get("code") or "invalid")
                for row in report.get("errors") or []
                if isinstance(row, dict)
            }
        )
        raise PackError(
            "active_pack_page_types_unverified",
            f"{pack_id}:{','.join(codes) or 'validation_failed'}",
        )
    raw, _record = _verified_pack_file(root, pack_id, entry, "pack.yaml")
    if hashlib.sha256(raw).hexdigest() != entry.get("manifest_sha256"):
        raise PackError("installed_manifest_hash_mismatch", pack_id)
    try:
        manifest = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise PackError("installed_manifest_invalid", pack_id) from exc
    if not isinstance(manifest, dict):
        raise PackError("installed_manifest_invalid", pack_id)
    if manifest.get("id") != pack_id or manifest.get("version") != entry.get("version"):
        raise PackError("installed_manifest_identity_mismatch", pack_id)
    for field in ("capabilities", "slots", "dependencies", "conflicts"):
        if manifest.get(field) != entry.get(field):
            raise PackError("installed_manifest_lock_mismatch", f"{pack_id}:{field}")
    if _canonical_sha256(entry.get("files")) != entry.get("tree_sha256"):
        raise PackError("installed_tree_lock_mismatch", pack_id)
    installed_root = root / str(entry["installed_path"])
    validate_manifest(root, installed_root, manifest)
    return installed_root, manifest


def _pack_template_shape(
    root: Path,
    *,
    pack_id: str,
    entry: dict[str, Any],
    manifest: dict[str, Any],
    page_type: str,
    spec: dict[str, Any],
    memory_root: str,
) -> dict[str, Any]:
    if set(spec) != _PACK_PAGE_TYPE_FIELDS:
        raise PackError("pack_page_type_fields_mismatch", f"{pack_id}:{page_type}")
    title = spec.get("title")
    visibility = spec.get("visibility")
    fields = spec.get("fields")
    if not isinstance(title, str) or not title.strip():
        raise PackError("pack_page_type_title_required", f"{pack_id}:{page_type}")
    if (
        visibility not in _PACK_PRIVATE_VISIBILITIES
        or visibility != manifest["privacy"]["default_visibility"]
    ):
        raise PackError("pack_page_type_privacy_mismatch", f"{pack_id}:{page_type}")
    if not isinstance(fields, list) or any(
        not isinstance(field, str) or not _PACK_FIELD_RE.fullmatch(field)
        for field in fields
    ):
        raise PackError("pack_page_type_fields_invalid", f"{pack_id}:{page_type}")
    if len(fields) != len(set(fields)):
        raise PackError("pack_page_type_fields_duplicate", f"{pack_id}:{page_type}")
    reserved = sorted(set(fields) & _PACK_RESERVED_FIELDS)
    if reserved:
        raise PackError("pack_page_type_reserved_field", f"{pack_id}:{reserved[0]}")

    template_relative = _safe_pack_relative(
        spec.get("template"),
        label=f"pack template:{pack_id}:{page_type}",
    )
    templates_root = _safe_pack_relative(
        manifest["artifacts"]["templates"],
        label=f"pack templates:{pack_id}",
    ).rstrip("/")
    if not template_relative.startswith(templates_root + "/"):
        raise PackError(
            "pack_template_outside_declared_artifact", f"{pack_id}:{page_type}"
        )
    template_raw, template_record = _verified_pack_file(
        root,
        pack_id,
        entry,
        template_relative,
    )
    try:
        template_text = template_raw.decode("utf-8")
    except UnicodeError as exc:
        raise PackError("pack_template_not_utf8", f"{pack_id}:{page_type}") from exc
    if not FRONTMATTER_RE.match(template_text):
        raise PackError("pack_template_frontmatter_required", f"{pack_id}:{page_type}")
    template_values, body = parse_frontmatter(template_text)
    if (
        template_values.get("page_type") != page_type
        or template_values.get("visibility") != visibility
    ):
        raise PackError("pack_template_identity_mismatch", f"{pack_id}:{page_type}")
    if set(template_values) != {"page_type", "visibility", *fields}:
        raise PackError(
            "pack_template_frontmatter_fields_mismatch",
            f"{pack_id}:{page_type}",
        )
    missing_fields = sorted(set(fields) - set(template_values))
    if missing_fields:
        raise PackError("pack_template_field_missing", f"{pack_id}:{missing_fields[0]}")
    if not body.strip():
        raise PackError("pack_template_body_required", f"{pack_id}:{page_type}")

    prefix = f"{pack_id.replace('-', '_')}_"
    suffix = page_type.removeprefix(prefix).replace("_", "-")
    installed_template = (
        Path(str(entry["installed_path"])) / template_relative
    ).as_posix()
    return {
        "template": installed_template,
        "allowed_dirs": [f"{memory_root}/packs/{pack_id}/{suffix}"],
        "required_frontmatter": [
            "page_id",
            "page_type",
            "title",
            "context",
            "visibility",
            "updated_at",
            "stale_after_days",
        ],
        "declared_frontmatter": list(fields),
        "field_types": {
            "updated_at": "date",
            "stale_after_days": "string",
        },
        "field_constants": {
            "page_type": page_type,
            "visibility": visibility,
        },
        "experience_pack": {
            "id": pack_id,
            "version": str(entry["version"]),
            "template_sha256": str(template_record["sha256"]),
            "template_size": int(template_record["size"]),
        },
    }


def _load_active_pack_page_types(
    root: Path,
    *,
    memory_root: str,
) -> dict[str, dict[str, Any]]:
    lock = load_lock(root)
    merged: dict[str, dict[str, Any]] = {}
    for pack_id, entry in sorted(lock["packs"].items()):
        if entry.get("status") != "active":
            continue
        _installed_root, manifest = _installed_manifest(root, pack_id, entry)
        relative = _safe_pack_relative(
            manifest["artifacts"]["page_types"],
            label=f"pack page types:{pack_id}",
        )
        raw, _record = _verified_pack_file(root, pack_id, entry, relative)
        try:
            document = yaml.safe_load(raw.decode("utf-8"))
        except (UnicodeError, yaml.YAMLError) as exc:
            raise PackError("pack_page_types_invalid", pack_id) from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "pack", "page_types"}
            or document.get("schema_version") != PACK_PAGE_TYPES_SCHEMA_VERSION
            or document.get("pack") != pack_id
            or not isinstance(document.get("page_types"), dict)
        ):
            raise PackError("pack_page_types_contract_mismatch", pack_id)
        declared = manifest["capabilities"]["page_types"]
        if set(document["page_types"]) != set(declared):
            raise PackError("pack_page_types_capability_mismatch", pack_id)
        for page_type in sorted(document["page_types"]):
            spec = document["page_types"][page_type]
            if not isinstance(spec, dict):
                raise PackError(
                    "pack_page_type_mapping_required", f"{pack_id}:{page_type}"
                )
            if page_type in merged:
                raise PackError("page_type_conflict", page_type)
            merged[page_type] = _pack_template_shape(
                root,
                pack_id=pack_id,
                entry=entry,
                manifest=manifest,
                page_type=page_type,
                spec=spec,
                memory_root=memory_root,
            )
    return merged


def list_values(value: Any) -> list[str]:
    """Shape-validator normalization (intentionally NON-stripping).

    This is the one ``list_values`` that does NOT delegate to the canonical
    :func:`wiki_core.frontmatter.list_values`. The shape gate validates raw
    frontmatter values verbatim (``field_type_error`` checks dates/enums against
    the exact text), so stripping here could silently change a gate verdict. It
    keeps items as-is, filtering only on truthiness after ``str(item)``, and does
    not strip the single-string case. See ``wiki_core.frontmatter`` for the
    differences this helper preserves.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        if value.strip() == "[]":
            return []
        return [value]
    return [str(value)]


def markdown_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(match.group(1).strip())
    return headings


def field_type_error(field: str, expected: str, value: Any) -> str | None:
    values = list_values(value)
    if expected == "string":
        if not isinstance(value, str) or not value.strip():
            return f"{field} must be a non-empty string"
    elif expected == "date":
        if not values or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[0]):
            return f"{field} must be an ISO date"
    elif expected == "date_or_instant":
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                return f"{field} must be an ISO date or offset instant"
        elif isinstance(value, dt.date):
            pass
        else:
            raw = str(value or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                try:
                    dt.date.fromisoformat(raw)
                except ValueError:
                    return f"{field} must be an ISO date or offset instant"
            elif re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
                raw,
            ):
                try:
                    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    return f"{field} must be an ISO date or offset instant"
                if parsed.tzinfo is None:
                    return f"{field} must be an ISO date or offset instant"
            else:
                return f"{field} must be an ISO date or offset instant"
    elif expected == "list":
        if not isinstance(value, list):
            return f"{field} must be a list"
    elif expected == "object":
        if not isinstance(value, dict):
            return f"{field} must be an object"
    elif expected == "bool":
        if str(value).lower() not in {
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
            "1",
            "0",
        }:
            return f"{field} must be boolean-like"
    elif expected.startswith("enum:"):
        allowed = {
            item.strip()
            for item in expected.split(":", 1)[1].split(",")
            if item.strip()
        }
        if not values or any(item not in allowed for item in values):
            return f"{field} must be one of {', '.join(sorted(allowed))}"
    return None


def template_coverage_error(
    root: Path, page_type: str, shape: dict[str, Any]
) -> str | None:
    template = shape.get("template")
    if template == "none":
        if not str(shape.get("template_none_reason") or "").strip():
            return f"page_type `{page_type}` has template: none without template_none_reason"
        return None
    if not template:
        return f"page_type `{page_type}` has no template"
    template_path = root / str(template)
    if not template_path.exists():
        return f"page_type `{page_type}` template does not exist: {template}"
    pack = shape.get("experience_pack")
    if isinstance(pack, dict):
        if not template_path.is_file() or template_path.is_symlink():
            return (
                f"page_type `{page_type}` installed pack template is not a regular file"
            )
        try:
            raw = template_path.read_bytes()
        except OSError:
            return f"page_type `{page_type}` installed pack template is unreadable"
        if len(raw) != pack.get("template_size") or hashlib.sha256(
            raw
        ).hexdigest() != pack.get("template_sha256"):
            return (
                f"page_type `{page_type}` installed pack template drifted from its lock"
            )
    return None


def _action_history_shape_errors(
    rel: str,
    values: dict[str, Any],
    action_state: str,
) -> list[str]:
    raw_history = values.get("action_state_history")
    if raw_history in (None, []):
        return []
    if not isinstance(raw_history, list):
        return [f"{rel}: `action_state_history` must be a list"]

    errors: list[str] = []
    page_id = str(values.get("page_id") or "").strip()
    prior_receipt_id = ""
    prior_state = ""
    prior_at: dt.datetime | None = None
    terminal_transition_at = ""
    for index, raw_entry in enumerate(raw_history):
        label = f"{rel}: action_state_history[{index}]"
        if not isinstance(raw_entry, dict):
            errors.append(f"{label} must be an object")
            continue
        entry = dict(raw_entry)
        schema_version = str(entry.get("schema_version") or "")
        if schema_version not in _ACTION_RECEIPT_SCHEMAS:
            errors.append(f"{label} has unsupported schema_version")
        if str(entry.get("page_id") or "") != page_id:
            errors.append(f"{label} page_id does not match the action")
        previous = str(entry.get("from") or "")
        target = str(entry.get("to") or "")
        if (
            previous not in CANONICAL_ACTION_STATES
            or target not in CANONICAL_ACTION_STATES
            or not valid_action_transition(previous, target)
        ):
            errors.append(f"{label} contains an invalid canonical transition")
        if prior_state and previous != prior_state:
            errors.append(f"{label} does not continue the prior receipt state")
        kind = str(entry.get("kind") or "")
        if previous == target:
            if kind not in {"legacy_canonicalization", "contract_update"}:
                errors.append(f"{label} has invalid state-preserving kind")
        elif kind != "transition":
            errors.append(f"{label} state change must use kind `transition`")

        receipt_id = str(entry.get("receipt_id") or "")
        canonical = {str(key): value for key, value in entry.items() if key != "receipt_id"}
        try:
            expected_receipt_id = "sha256:" + hashlib.sha256(
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError):
            expected_receipt_id = ""
        if not _RECEIPT_ID_RE.fullmatch(receipt_id) or receipt_id != expected_receipt_id:
            errors.append(f"{label} receipt_id does not bind its payload")
        if str(entry.get("prior_receipt_id") or "") != prior_receipt_id:
            errors.append(f"{label} does not extend the prior receipt id")
        for field in (
            "before_sha256",
            "before_revision",
            "payload_sha256",
            "governed_support_sha256",
        ):
            if not _SHA256_RE.fullmatch(str(entry.get(field) or "")):
                errors.append(f"{label} is missing `{field}`")

        support_fields = entry.get("support_fields")
        allowed_support = (
            _ACTION_SUPPORT_FIELDS_V1
            if schema_version == "wiki_action_transition_receipt.v1"
            else _ACTION_SUPPORT_FIELDS_V2
        )
        if (
            not isinstance(support_fields, list)
            or support_fields != sorted(set(support_fields))
            or any(str(field) not in allowed_support for field in support_fields)
        ):
            errors.append(f"{label} has invalid governed support fields")

        at = str(entry.get("at") or "")
        parsed_at: dt.datetime | None = None
        if _ACTION_INSTANT_RE.fullmatch(at):
            try:
                parsed_at = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
            except ValueError:
                parsed_at = None
        if parsed_at is None or parsed_at.tzinfo is None:
            errors.append(f"{label} has invalid offset-aware timestamp")
        elif prior_at is not None and (
            parsed_at < prior_at
            or (
                schema_version == "wiki_action_transition_receipt.v2"
                and parsed_at == prior_at
            )
        ):
            errors.append(f"{label} timestamp is not causally monotonic")
        if parsed_at is not None:
            prior_at = parsed_at

        if target in {"done", "cancelled"} and (
            previous != target
            or (
                isinstance(support_fields, list)
                and "completed_at" in support_fields
            )
        ):
            terminal_transition_at = at
        prior_state = target
        prior_receipt_id = receipt_id

    if prior_state and prior_state != action_state:
        errors.append(
            f"{rel}: action_state_history does not end at canonical `action_state`"
        )
    if terminal_transition_at and str(values.get("completed_at") or "").strip() != (
        terminal_transition_at
    ):
        errors.append(
            f"{rel}: terminal `completed_at` must match its transition receipt instant"
        )
    return errors


def validate_shape(
    root: Path,
    rel: str,
    values: dict[str, Any],
    text: str,
    shape: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in shape.get("required_frontmatter") or []:
        if field not in values or values[field] in ("", [], None):
            errors.append(f"{rel}: missing required shape field `{field}`")
    for field in shape.get("declared_frontmatter") or []:
        if field not in values:
            errors.append(f"{rel}: missing declared pack field `{field}`")
    for field, expected in (shape.get("field_constants") or {}).items():
        if values.get(field) != expected:
            errors.append(
                f"{rel}: `{field}` must remain `{expected}` for this page type"
            )
    for field, expected in (shape.get("field_types") or {}).items():
        if field in values:
            error = field_type_error(str(field), str(expected), values[field])
            if error:
                errors.append(f"{rel}: {error}")
    if str(values.get("page_type") or "") == "action":
        action_state = resolve_action_state(values).state
        errors.extend(_action_history_shape_errors(rel, values, action_state))
        next_action = str(values.get("next_action") or "").strip()
        blocker_reason = str(values.get("blocker_reason") or "").strip()
        blocked_by = list_values(values.get("blocked_by"))
        completed_at = str(values.get("completed_at") or "").strip()
        completion_receipt = str(values.get("completion_receipt") or "").strip()
        cancellation_receipt = str(
            values.get("cancellation_receipt") or ""
        ).strip()
        if (
            action_state in NON_TERMINAL_ACTION_STATES
            and not next_action
        ):
            errors.append(f"{rel}: non-terminal action requires `next_action`")
        if action_state in {"done", "cancelled"} and next_action:
            errors.append(f"{rel}: terminal action forbids `next_action`")
        if (
            action_state == "blocked"
            and not blocker_reason
        ):
            errors.append(f"{rel}: blocked action requires `blocker_reason`")
        if action_state != "blocked" and blocker_reason:
            errors.append(
                f"{rel}: only blocked action may carry `blocker_reason`"
            )
        if action_state != "blocked" and blocked_by:
            errors.append(f"{rel}: only blocked action may carry `blocked_by`")
        if (
            action_state == "done"
            and not completion_receipt
        ):
            errors.append(f"{rel}: done action requires `completion_receipt`")
        if action_state != "done" and completion_receipt:
            errors.append(
                f"{rel}: only done action may carry `completion_receipt`"
            )
        if (
            action_state == "cancelled"
            and not cancellation_receipt
        ):
            errors.append(f"{rel}: cancelled action requires `cancellation_receipt`")
        if action_state != "cancelled" and cancellation_receipt:
            errors.append(
                f"{rel}: only cancelled action may carry `cancellation_receipt`"
            )
        if action_state in {"done", "cancelled"} and not completed_at:
            errors.append(f"{rel}: terminal action requires `completed_at`")
        if action_state in NON_TERMINAL_ACTION_STATES and completed_at:
            errors.append(
                f"{rel}: non-terminal action forbids `completed_at`"
            )
    allowed_dirs = [str(item).rstrip("/") for item in (shape.get("allowed_dirs") or [])]
    if allowed_dirs and not any(
        rel.startswith(prefix + "/") or rel == prefix for prefix in allowed_dirs
    ):
        errors.append(
            f"{rel}: page_type `{values.get('page_type')}` not allowed in this directory"
        )
    headings = markdown_headings(text)
    for section in shape.get("required_sections") or []:
        if str(section) not in headings:
            errors.append(f"{rel}: missing required section `{section}`")
    return errors
