"""Safe, reviewable source configuration operations for the local cockpit.

The browser never submits an argv or an arbitrary file path.  It submits a
small typed patch for one source stream, receives a content-bound preview, and
must return the exact preview token before the operator writes anything.
Receipts live under the derived cache: configuration changes remain visible in
Git while operational evidence does not pollute the canonical wiki.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from wiki_core.config import WikiConfig
from wiki_core.detectors import scan_text
from wiki_core.paths import WikiPaths
from wiki_core.source_recipe import extract_recipe_mapping, parse_recipe, validate_recipe
from wiki_core.source_schedule import SCHEDULE_MODES, SOURCE_KINDS
from wiki_core.web.sources import build_sources_payload
from wiki_core.web.commands import SECRET_VALUE_RE

SOURCE_OPERATION_SCHEMA_VERSION = "wiki_source_operation.v1"
SOURCE_INVENTORY_SCHEMA_VERSION = "wiki_source_inventory.v1"
_MAX_INVENTORY_BYTES = 2_000_000
_MAX_INVENTORY_RECORDS = 10_000
_YAML_BLOCK_RE = re.compile(r"```ya?ml\n(.*?)\n```", re.S)
_PRIVACY = {"private_self", "private_sensitive_allowed", "team_shared", "public_ok"}
_ALLOWED_UPDATES = {
    "label",
    "selected",
    "privacy",
    "cadence_days",
    "skip_reason",
    "target_pages",
    "processing_state",
}
_ALLOWED_SOURCE_UPDATES = {"source_kind", "schedule_mode", "schedule_cadence_days"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_repo_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("source_operation_invalid_path")
    root_resolved = root.resolve()
    candidate = (root / relative).resolve(strict=True)
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        raise ValueError("source_operation_invalid_path")
    return candidate


def _source(root: Path, config: WikiConfig, source_id: str) -> dict[str, Any]:
    payload = build_sources_payload(root, config)
    source = next((item for item in payload["sources"] if item["source_id"] == source_id), None)
    if source is None:
        raise ValueError("source_operation_unknown_source")
    if not source.get("recipe_ok"):
        raise ValueError("source_operation_invalid_recipe")
    return source


def _normalize_updates(updates: Any) -> dict[str, Any]:
    if not isinstance(updates, dict) or not updates:
        raise ValueError("source_operation_empty_updates")
    unknown = sorted(set(updates) - _ALLOWED_UPDATES)
    if unknown:
        raise ValueError("source_operation_unknown_field:" + ",".join(unknown))
    out: dict[str, Any] = {}
    if "label" in updates:
        label = str(updates["label"]).strip()
        if not label or len(label) > 240:
            raise ValueError("source_operation_invalid_label")
        out["label"] = label
    if "selected" in updates:
        if not isinstance(updates["selected"], bool):
            raise ValueError("source_operation_invalid_selected")
        out["selected"] = updates["selected"]
    if "privacy" in updates:
        privacy = str(updates["privacy"]).strip()
        if privacy not in _PRIVACY:
            raise ValueError("source_operation_invalid_privacy")
        out["privacy"] = privacy
    if "cadence_days" in updates:
        value = updates["cadence_days"]
        if isinstance(value, bool):
            raise ValueError("source_operation_invalid_cadence")
        try:
            cadence = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_operation_invalid_cadence") from exc
        if cadence < 0 or cadence > 3650:
            raise ValueError("source_operation_invalid_cadence")
        out["cadence_days"] = cadence
    if "skip_reason" in updates:
        reason = str(updates["skip_reason"]).strip()
        if len(reason) > 800:
            raise ValueError("source_operation_invalid_skip_reason")
        out["skip_reason"] = reason
    if "target_pages" in updates:
        targets = updates["target_pages"]
        if not isinstance(targets, list) or len(targets) > 64:
            raise ValueError("source_operation_invalid_targets")
        normalized = []
        for target in targets:
            value = str(target).strip()
            if not value or value.startswith("/") or ".." in Path(value).parts or len(value) > 300:
                raise ValueError("source_operation_invalid_targets")
            if value not in normalized:
                normalized.append(value)
        out["target_pages"] = normalized
    if "processing_state" in updates:
        state = str(updates["processing_state"]).strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", state):
            raise ValueError("source_operation_invalid_processing_state")
        out["processing_state"] = state
    return out


def _normalize_source_updates(updates: Any) -> dict[str, Any]:
    if not isinstance(updates, dict) or not updates:
        raise ValueError("source_operation_empty_updates")
    unknown = sorted(set(updates) - _ALLOWED_SOURCE_UPDATES)
    if unknown:
        raise ValueError("source_operation_unknown_field:" + ",".join(unknown))
    out: dict[str, Any] = {}
    if "source_kind" in updates:
        source_kind = str(updates["source_kind"]).strip()
        if source_kind not in SOURCE_KINDS:
            raise ValueError("source_operation_invalid_source_kind")
        out["source_kind"] = source_kind
    if "schedule_mode" in updates:
        schedule_mode = str(updates["schedule_mode"]).strip()
        if schedule_mode not in SCHEDULE_MODES:
            raise ValueError("source_operation_invalid_schedule_mode")
        out["schedule_mode"] = schedule_mode
    if "schedule_cadence_days" in updates:
        value = updates["schedule_cadence_days"]
        if isinstance(value, bool):
            raise ValueError("source_operation_invalid_schedule_cadence")
        try:
            cadence = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_operation_invalid_schedule_cadence") from exc
        if cadence < 0 or cadence > 3650:
            raise ValueError("source_operation_invalid_schedule_cadence")
        out["schedule_cadence_days"] = cadence
    mode = str(out.get("schedule_mode") or "")
    cadence = out.get("schedule_cadence_days")
    if mode and mode != "recurring" and cadence not in (None, 0):
        raise ValueError("source_operation_non_recurring_cadence")
    if mode == "recurring" and cadence == 0:
        raise ValueError("source_operation_recurring_cadence_required")
    return out


def _patched_recipe(recipe: dict[str, Any], stream_id: str, updates: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    copied = json.loads(json.dumps(recipe))
    if stream_id == "__source__":
        schedule = copied.get("schedule")
        if not isinstance(schedule, dict):
            schedule = {"mode": "on_demand", "cadence_days": 0}
            copied["schedule"] = schedule
        before = {
            "source_kind": str(copied.get("source_kind") or ""),
            "schedule_mode": str(schedule.get("mode") or ""),
            "schedule_cadence_days": int(schedule.get("cadence_days") or 0),
        }
        for key, value in updates.items():
            if key == "source_kind":
                copied["source_kind"] = value
            elif key == "schedule_mode":
                schedule["mode"] = value
                if value != "recurring" and "schedule_cadence_days" not in updates:
                    schedule["cadence_days"] = 0
            elif key == "schedule_cadence_days":
                schedule["cadence_days"] = value
        after = {
            "source_kind": str(copied.get("source_kind") or ""),
            "schedule_mode": str(schedule.get("mode") or ""),
            "schedule_cadence_days": int(schedule.get("cadence_days") or 0),
        }
        return copied, {"before": before, "after": after}
    streams = copied.get("streams")
    if not isinstance(streams, list):
        raise ValueError("source_operation_invalid_recipe")
    stream = next((item for item in streams if isinstance(item, dict) and str(item.get("id")) == stream_id), None)
    if stream is None:
        raise ValueError("source_operation_unknown_stream")
    before = {
        "label": stream.get("label", stream_id),
        "selected": bool(stream.get("selected", True)),
        "privacy": stream.get("privacy", "private_self"),
        "cadence_days": int(stream.get("cadence_days") or 0),
        "skip_reason": str(stream.get("skip_reason") or ""),
        "target_pages": list(stream.get("target_pages") or []),
        "processing_state": str((stream.get("filters") or {}).get("processing_state") or ""),
    }
    for key, value in updates.items():
        if key == "processing_state":
            filters = stream.get("filters")
            if not isinstance(filters, dict):
                filters = {}
                stream["filters"] = filters
            filters["processing_state"] = value
        elif key == "skip_reason":
            if value:
                stream[key] = value
            else:
                stream.pop(key, None)
        else:
            stream[key] = value
    after = dict(before)
    after.update(updates)
    return copied, {"before": before, "after": after}


def _replace_recipe(text: str, recipe: dict[str, Any]) -> str:
    replacement = yaml.safe_dump({"recipe": recipe}, sort_keys=False, allow_unicode=True).rstrip("\n")
    for match in _YAML_BLOCK_RE.finditer(text):
        try:
            mapping = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if not isinstance(mapping, dict):
            continue
        if isinstance(mapping.get("recipe"), dict) or str(mapping.get("schema_version") or "").startswith("wiki_source_recipe"):
            return text[: match.start()] + "```yaml\n" + replacement + "\n```" + text[match.end() :]
    raise ValueError("source_operation_recipe_block_missing")


def preview_source_operation(
    root: Path,
    config: WikiConfig,
    source_id: str,
    stream_id: str,
    updates: Any,
) -> dict[str, Any]:
    source = _source(root, config, source_id)
    normalized = _normalize_source_updates(updates) if stream_id == "__source__" else _normalize_updates(updates)
    config_path = _safe_repo_file(root, str(source.get("config_ref") or ""))
    text = config_path.read_text(encoding="utf-8")
    recipe = extract_recipe_mapping(text)
    if recipe is None:
        raise ValueError("source_operation_recipe_block_missing")
    patched, state = _patched_recipe(recipe, stream_id, normalized)
    validation = validate_recipe(parse_recipe(patched))
    if validation:
        raise ValueError("source_operation_invalid_result:" + ",".join(validation))
    changed = [
        {"field": key, "before": state["before"].get(key), "after": state["after"].get(key)}
        for key in normalized
        if state["before"].get(key) != state["after"].get(key)
    ]
    if not changed:
        raise ValueError("source_operation_no_changes")
    rendered = _replace_recipe(text, patched)
    recipe_model = parse_recipe(patched)
    selected_stream = None if stream_id == "__source__" else next(item for item in source["streams"] if item["id"] == stream_id)
    token_material = {
        "schema": SOURCE_OPERATION_SCHEMA_VERSION,
        "source_id": source_id,
        "stream_id": stream_id,
        "config_sha256": _sha(text),
        "result_sha256": _sha(rendered),
        "updates": normalized,
    }
    preview_token = _sha(json.dumps(token_material, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    execution_mode = (
        "deterministic_connector"
        if recipe_model.refresh_argv
        else "script"
        if recipe_model.ingest_argv
        else "agent_connector"
        if recipe_model.mcp_hint
        else "manual_export"
    )
    return {
        "ok": True,
        "schema_version": SOURCE_OPERATION_SCHEMA_VERSION,
        "source_id": source_id,
        "stream_id": stream_id,
        "preview_token": preview_token,
        "config_ref": str(config_path.relative_to(root)),
        "config_sha256": token_material["config_sha256"],
        "result_sha256": token_material["result_sha256"],
        "changes": changed,
        "updates": normalized,
        "raw_inventory": {
            "scope": "source" if stream_id == "__source__" else "record",
            "platform": source.get("platform"),
            "locator": source.get("locator"),
            "source_kind": source.get("source_kind"),
            "schedule": source.get("schedule"),
            **({
                "filters": selected_stream.get("filters") or {},
                "privacy": selected_stream.get("privacy"),
                "target_pages": selected_stream.get("target_pages") or [],
                "freshness_basis": selected_stream.get("freshness_basis"),
            } if selected_stream is not None else {"records": len(source.get("streams") or [])}),
        },
        "execution": {
            "mode": execution_mode,
            "argv": list(recipe_model.ingest_argv),
            "mcp_hint": recipe_model.mcp_hint,
            "how_to_export": recipe_model.how_to_export,
        },
        "steps": [
            {"id": "bind", "label": "Confirm source configuration" if stream_id == "__source__" else "Confirm source and selected record", "status": "complete"},
            {"id": "inventory", "label": "Capture deterministic raw metadata", "status": "complete"},
            {"id": "validate", "label": "Validate the resulting recipe", "status": "complete"},
            {"id": "write", "label": "Write only after explicit confirmation", "status": "pending"},
            {"id": "receipt", "label": "Persist an operation receipt", "status": "pending"},
        ],
    }


def apply_source_operation(
    root: Path,
    config: WikiConfig,
    source_id: str,
    stream_id: str,
    updates: Any,
    preview_token: str,
) -> dict[str, Any]:
    preview = preview_source_operation(root, config, source_id, stream_id, updates)
    if not preview_token or preview_token != preview["preview_token"]:
        raise ValueError("source_operation_preview_stale")
    config_path = _safe_repo_file(root, preview["config_ref"])
    current = config_path.read_text(encoding="utf-8")
    if _sha(current) != preview["config_sha256"]:
        raise ValueError("source_operation_preview_stale")
    recipe = extract_recipe_mapping(current)
    if recipe is None:
        raise ValueError("source_operation_recipe_block_missing")
    patched, _ = _patched_recipe(recipe, stream_id, preview["updates"])
    rendered = _replace_recipe(current, patched)
    if _sha(rendered) != preview["result_sha256"]:
        raise ValueError("source_operation_preview_stale")
    temporary = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(config_path)
    finally:
        temporary.unlink(missing_ok=True)

    operation_id = "sop-" + uuid.uuid4().hex[:12]
    receipt = {
        "schema_version": SOURCE_OPERATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "recorded_at": _now(),
        "source_id": source_id,
        "stream_id": stream_id,
        "preview_token": preview_token,
        "config_ref": preview["config_ref"],
        "result_sha256": preview["result_sha256"],
        "changes": preview["changes"],
        "status": "applied",
    }
    receipt_dir = WikiPaths(root, config).derived_root / "source-operations"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{operation_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        **receipt,
        "receipt_path": str(receipt_path.relative_to(root)),
        "changed_files": [preview["config_ref"]],
        "source": _source(root, config, source_id),
    }


def list_source_operation_receipts(root: Path, config: WikiConfig, source_id: str) -> list[dict[str, Any]]:
    receipt_dir = WikiPaths(root, config).derived_root / "source-operations"
    records: list[dict[str, Any]] = []
    if not receipt_dir.is_dir():
        return records
    for path in receipt_dir.glob("sop-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("source_id") == source_id:
            records.append(record)
    records.sort(key=lambda item: str(item.get("recorded_at") or ""), reverse=True)
    return records[:20]


def _safe_raw_path(root: Path, config: WikiConfig, value: str) -> Path:
    if not value or Path(value).is_absolute():
        raise ValueError("source_refresh_raw_path_required")
    root_resolved = root.resolve()
    raw_root = WikiPaths(root, config).raw_root.resolve()
    candidate = (root / value).resolve(strict=True)
    if not candidate.is_relative_to(root_resolved) or not candidate.is_relative_to(raw_root) or not (candidate.is_file() or candidate.is_dir()):
        raise ValueError("source_refresh_raw_path_invalid")
    return candidate


def _inventory_raw_path(root: Path, raw_path: Path) -> tuple[dict[str, Any], str]:
    """Build a deterministic inventory for a RAW item or collection.

    Folder refresh is the primary contract: every file is sorted by relative
    path and content-hashed so a later snapshot can classify additions,
    changes and removals without depending on filesystem enumeration order.
    """
    files = [raw_path] if raw_path.is_file() else sorted(path for path in raw_path.rglob("*") if path.is_file())
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    digest = hashlib.sha256()
    for path in files:
        content = path.read_bytes()
        relative = path.relative_to(raw_path.parent if raw_path.is_file() else raw_path).as_posix()
        sha256 = hashlib.sha256(content).hexdigest()
        stat = path.stat()
        total_bytes += stat.st_size
        entry = {
            "path": relative,
            "sha256": sha256,
            "size_bytes": stat.st_size,
            "modified_at_ns": stat.st_mtime_ns,
        }
        entries.append(entry)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")
    return {
        "path": raw_path.relative_to(root).as_posix(),
        "kind": "file" if raw_path.is_file() else "collection",
        "item_count": len(entries),
        "total_bytes": total_bytes,
        "sha256": digest.hexdigest(),
        "entries": entries,
    }, digest.hexdigest()


def _safe_refresh_argv(
    root: Path,
    argv: tuple[str, ...],
    *,
    source_id: str,
    locator: str,
    config_ref: str,
) -> list[str]:
    """Render one repository-owned, deterministic inventory adapter.

    The shared core still owns process safety and the JSON contract; provider
    authentication and API logic stay in the consumer-owned script.
    """
    if not argv:
        raise ValueError("source_refresh_adapter_unavailable")
    replacements = {
        "{source_id}": source_id,
        "{locator}": locator,
        "{config_ref}": config_ref,
    }
    rendered: list[str] = []
    for part in argv:
        value = str(part)
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        rendered.append(value)
    if rendered[0] not in {"python", "python3"} or len(rendered) < 2:
        raise ValueError("source_refresh_adapter_not_allowlisted")
    script = Path(rendered[1])
    if script.is_absolute() or script.suffix != ".py" or not script.parts or script.parts[0] != "scripts":
        raise ValueError("source_refresh_adapter_not_allowlisted")
    script_path = (root / script).resolve(strict=True)
    if not script_path.is_relative_to((root / "scripts").resolve()) or not script_path.is_file():
        raise ValueError("source_refresh_adapter_not_allowlisted")
    if any("{" in part or "}" in part for part in rendered):
        raise ValueError("source_refresh_unresolved_placeholder")
    return rendered


def _normalize_inventory(payload: Any, *, source_id: str, locator: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SOURCE_INVENTORY_SCHEMA_VERSION:
        raise ValueError("source_refresh_inventory_contract_invalid")
    if payload.get("source_id") not in (None, "", source_id) or payload.get("locator") not in (None, "", locator):
        raise ValueError("source_refresh_inventory_subject_mismatch")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or len(raw_records) > _MAX_INVENTORY_RECORDS:
        raise ValueError("source_refresh_inventory_records_invalid")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError("source_refresh_inventory_record_invalid")
        external_id = str(raw.get("external_id") or "").strip()
        label = str(raw.get("label") or "").strip()
        filters = raw.get("filters")
        if (
            not external_id
            or len(external_id) > 512
            or not label
            or len(label) > 500
            or not isinstance(filters, dict)
            or external_id in seen
        ):
            raise ValueError("source_refresh_inventory_record_invalid")
        try:
            serialized = json.dumps(filters, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_refresh_inventory_record_invalid") from exc
        if len(serialized.encode("utf-8")) > 100_000:
            raise ValueError("source_refresh_inventory_record_too_large")
        probe = json.dumps({"external_id": external_id, "label": label, "filters": filters}, ensure_ascii=False)
        if any(finding.category == "secret" for finding in scan_text(probe)):
            raise ValueError("source_refresh_inventory_secret_detected")
        clean_filters = dict(filters)
        clean_filters.pop("processing_state", None)
        records.append({"external_id": external_id, "label": label, "filters": clean_filters})
        seen.add(external_id)
    records.sort(key=lambda item: (item["label"].casefold(), item["external_id"]))
    normalized = {
        "schema_version": SOURCE_INVENTORY_SCHEMA_VERSION,
        "source_id": source_id,
        "locator": locator,
        "records": records,
    }
    if len(json.dumps(normalized, ensure_ascii=False).encode("utf-8")) > _MAX_INVENTORY_BYTES:
        raise ValueError("source_refresh_inventory_too_large")
    return normalized


def _run_refresh_adapter(argv: list[str], *, root: Path, timeout_seconds: int = 60) -> tuple[dict[str, Any], str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("source_refresh_adapter_timeout") from exc
    if completed.returncode != 0:
        raise ValueError("source_refresh_adapter_failed")
    if len(completed.stdout.encode("utf-8")) > _MAX_INVENTORY_BYTES:
        raise ValueError("source_refresh_inventory_too_large")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("source_refresh_inventory_json_invalid") from exc
    # Adapter stderr is provider-controlled and may contain credentials or URLs.
    # The portable core exposes only its stable error code and validated JSON.
    return payload, ""


def _stream_external_id(stream: dict[str, Any]) -> str:
    filters = stream.get("filters") if isinstance(stream.get("filters"), dict) else {}
    return str(filters.get("external_id") or filters.get("file_id") or filters.get("record_id") or stream.get("id") or "")


def _inventory_diff(source: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    current_by_external = {_stream_external_id(stream): stream for stream in source.get("streams") or []}
    records: list[dict[str, Any]] = []
    counts = {"new": 0, "changed": 0, "enriched": 0, "unchanged": 0}
    for record in inventory["records"]:
        existing = current_by_external.get(record["external_id"])
        if existing is None:
            status = "new"
            before = None
            stream_id = ""
        else:
            current_filters = existing.get("filters") if isinstance(existing.get("filters"), dict) else {}
            before_filters = {key: current_filters.get(key) for key in record["filters"]}
            before = {"label": existing.get("label") or existing.get("id"), "filters": before_filters}
            after = {"label": record["label"], "filters": record["filters"]}
            if before == after:
                status = "unchanged"
            else:
                common_hashes = [
                    key
                    for key in ("checksum", "md5_checksum", "sha256")
                    if current_filters.get(key) not in (None, "")
                    and record["filters"].get(key) not in (None, "")
                ]
                content_changed = any(
                    current_filters.get(key) != record["filters"].get(key)
                    for key in common_hashes
                )
                if not common_hashes:
                    content_changed = (
                        current_filters.get("size_bytes") not in (None, "")
                        and record["filters"].get("size_bytes") not in (None, "")
                        and current_filters.get("size_bytes") != record["filters"].get("size_bytes")
                    )
                status = "changed" if content_changed else "enriched"
            stream_id = str(existing.get("id") or "")
        counts[status] += 1
        records.append({**record, "status": status, "stream_id": stream_id, "before": before})
    fingerprint = _sha(json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {"counts": counts, "records": records, "fingerprint": fingerprint}


def _new_stream_id(label: str, external_id: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:48] or "record"
    candidate = f"{base}-{hashlib.sha256(external_id.encode('utf-8')).hexdigest()[:8]}"
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _apply_inventory_to_recipe(
    recipe: dict[str, Any],
    source: dict[str, Any],
    discovery: dict[str, Any],
    selected_external_ids: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    copied = json.loads(json.dumps(recipe))
    streams = copied.get("streams")
    if not isinstance(streams, list):
        raise ValueError("source_operation_invalid_recipe")
    current_by_external = {
        _stream_external_id(stream): stream
        for stream in streams
        if isinstance(stream, dict)
    }
    used = {str(stream.get("id") or "") for stream in streams if isinstance(stream, dict)}
    inherited = next((stream for stream in streams if isinstance(stream, dict) and stream.get("selected", True)), None)
    default_privacy = str((inherited or {}).get("privacy") or "private_self")
    default_targets = list((inherited or {}).get("target_pages") or [source["path"]])
    default_cadence = int((inherited or {}).get("cadence_days") or 0)
    changes: list[dict[str, Any]] = []
    for record in discovery["records"]:
        if record["status"] not in {"new", "changed", "enriched"} or record["external_id"] not in selected_external_ids:
            continue
        existing = current_by_external.get(record["external_id"])
        if existing is None:
            stream_id = _new_stream_id(record["label"], record["external_id"], used)
            filters = {**record["filters"], "external_id": record["external_id"], "processing_state": "discovered"}
            created = {
                "id": stream_id,
                "label": record["label"],
                "selected": True,
                "privacy": default_privacy,
                "cadence_days": default_cadence,
                "filters": filters,
                "target_pages": default_targets,
            }
            streams.append(created)
            changes.append({"field": f"record:{record['external_id']}", "before": None, "after": created})
            continue
        before = json.loads(json.dumps(existing))
        existing["label"] = record["label"]
        filters = existing.get("filters") if isinstance(existing.get("filters"), dict) else {}
        content_changed = any(
            filters.get(key) not in (None, "")
            and record["filters"].get(key) not in (None, "")
            and filters.get(key) != record["filters"].get(key)
            for key in ("checksum", "md5_checksum", "sha256", "size_bytes")
        )
        filters.update(record["filters"])
        filters["external_id"] = record["external_id"]
        if content_changed and existing.get("selected", True) and str(filters.get("processing_state") or "") not in {"covered", "no_ingest"}:
            filters["processing_state"] = "changed"
        existing["filters"] = filters
        changes.append({"field": f"record:{record['external_id']}", "before": before, "after": existing})
    return copied, changes


def _safe_ingest_argv(root: Path, argv: tuple[str, ...], raw_path: Path) -> list[str]:
    if not argv:
        raise ValueError("source_refresh_script_unavailable")
    rendered = [str(part).replace("{path}", str(raw_path)) for part in argv]
    if rendered[0] not in {"python", "python3"} or len(rendered) < 2:
        raise ValueError("source_refresh_script_not_allowlisted")
    script = Path(rendered[1])
    if script.is_absolute() or script.suffix != ".py" or not script.parts or script.parts[0] != "scripts":
        raise ValueError("source_refresh_script_not_allowlisted")
    script_path = (root / script).resolve(strict=True)
    if not script_path.is_relative_to((root / "scripts").resolve()) or not script_path.is_file():
        raise ValueError("source_refresh_script_not_allowlisted")
    if any("{" in part or "}" in part for part in rendered):
        raise ValueError("source_refresh_unresolved_placeholder")
    return rendered


def preview_source_refresh(
    root: Path,
    config: WikiConfig,
    source_id: str,
    stream_id: str = "__source__",
    raw_path: str = "",
) -> dict[str, Any]:
    source = _source(root, config, source_id)
    config_path = _safe_repo_file(root, str(source.get("config_ref") or ""))
    config_text = config_path.read_text(encoding="utf-8")
    recipe_mapping = extract_recipe_mapping(config_text)
    if recipe_mapping is None:
        raise ValueError("source_operation_recipe_block_missing")
    recipe = parse_recipe(recipe_mapping)
    mode = (
        "deterministic_connector"
        if recipe.refresh_argv
        else "script"
        if recipe.ingest_argv
        else "agent_connector"
        if recipe.mcp_hint
        else "manual_export"
    )
    argv: list[str] = []
    discovery: dict[str, Any] | None = None
    adapter_stderr = ""
    raw: dict[str, Any] = {
        "scope": "source",
        "source_kind": source.get("source_kind"),
        "schedule_mode": (source.get("schedule") or {}).get("mode"),
        "platform": source.get("platform"),
        "locator": source.get("locator"),
        "records": [
            {
                "id": item.get("id"),
                "selected": item.get("selected", True),
                "filters": item.get("filters") or {},
                "privacy": item.get("privacy"),
                "target_pages": item.get("target_pages") or [],
                "cursor_age_days": item.get("cursor_age_days"),
                "freshness_basis": item.get("freshness_basis"),
            }
            for item in source["streams"]
        ],
    }
    raw_sha = ""
    normalized_raw_path = ""
    if mode == "deterministic_connector":
        argv = _safe_refresh_argv(
            root,
            recipe.refresh_argv,
            source_id=source_id,
            locator=str(source.get("locator") or ""),
            config_ref=str(source.get("config_ref") or ""),
        )
        payload, adapter_stderr = _run_refresh_adapter(argv, root=root)
        inventory = _normalize_inventory(
            payload,
            source_id=source_id,
            locator=str(source.get("locator") or ""),
        )
        discovery = _inventory_diff(source, inventory)
        raw["external_inventory"] = inventory
        raw_sha = discovery["fingerprint"]
    elif mode == "script":
        raw_file = _safe_raw_path(root, config, raw_path)
        normalized_raw_path = str(raw_file.relative_to(root))
        raw["local_raw"], raw_sha = _inventory_raw_path(root, raw_file)
        argv = _safe_ingest_argv(root, recipe.ingest_argv, raw_file)
    token_material = {
        "schema": SOURCE_OPERATION_SCHEMA_VERSION,
        "kind": "refresh",
        "source_id": source_id,
        "stream_id": stream_id,
        "config_sha256": _sha(config_text),
        "raw_sha256": raw_sha,
        "raw_path": normalized_raw_path,
        "mode": mode,
        "argv": argv,
        "discovery_sha256": discovery.get("fingerprint") if discovery else "",
    }
    token = _sha(json.dumps(token_material, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return {
        "ok": True,
        "schema_version": SOURCE_OPERATION_SCHEMA_VERSION,
        "kind": "refresh",
        "source_id": source_id,
        "stream_id": stream_id,
        "preview_token": token,
        "config_ref": str(config_path.relative_to(root)),
        "config_sha256": token_material["config_sha256"],
        "raw_path": normalized_raw_path,
        "raw_inventory": raw,
        "discovery": discovery,
        "execution": {
            "mode": mode,
            "argv": argv,
            "mcp_hint": recipe.mcp_hint,
            "how_to_export": recipe.how_to_export,
            "runnable": mode in {"script", "deterministic_connector"},
            "requires_agent": mode == "agent_connector",
            "stderr": SECRET_VALUE_RE.sub(
                lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
                adapter_stderr,
            )[:20_000],
        },
        "steps": [
            {"id": "bind", "label": "Confirm source and collection scope", "status": "complete"},
            {"id": "inventory", "label": "Inventory the whole source and detect record changes", "status": "complete"},
            {"id": "execute", "label": "Apply selected inventory records" if mode == "deterministic_connector" else "Run the allowlisted ingestion script", "status": "ready" if mode in {"script", "deterministic_connector"} else "delegated" if mode == "agent_connector" else "blocked"},
            {"id": "review", "label": "Review emitted event and file diff", "status": "pending"},
            {"id": "receipt", "label": "Persist execution receipt", "status": "pending"},
        ],
    }


def run_source_refresh(
    root: Path,
    config: WikiConfig,
    source_id: str,
    stream_id: str,
    raw_path: str,
    preview_token: str,
    selected_external_ids: Any = None,
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    preview = preview_source_refresh(root, config, source_id, stream_id, raw_path)
    mode = str(preview.get("execution", {}).get("mode") or "")
    if mode not in {"script", "deterministic_connector"}:
        raise ValueError("source_refresh_requires_agent_or_manual_export")
    if not preview_token or preview_token != preview["preview_token"]:
        raise ValueError("source_operation_preview_stale")
    if mode == "deterministic_connector":
        if selected_external_ids is None:
            selected_external_ids = []
        if not isinstance(selected_external_ids, list) or len(selected_external_ids) > _MAX_INVENTORY_RECORDS:
            raise ValueError("source_refresh_selected_records_invalid")
        selected = {str(value).strip() for value in selected_external_ids if str(value).strip()}
        discovery = preview.get("discovery") or {"counts": {}, "records": []}
        actionable = {
            str(record.get("external_id") or "")
            for record in discovery.get("records") or []
            if record.get("status") in {"new", "changed", "enriched"}
        }
        if not selected <= actionable:
            raise ValueError("source_refresh_selected_records_invalid")
        source = _source(root, config, source_id)
        config_path = _safe_repo_file(root, preview["config_ref"])
        current = config_path.read_text(encoding="utf-8")
        if _sha(current) != preview["config_sha256"]:
            raise ValueError("source_operation_preview_stale")
        recipe = extract_recipe_mapping(current)
        if recipe is None:
            raise ValueError("source_operation_recipe_block_missing")
        patched, changes = _apply_inventory_to_recipe(recipe, source, discovery, selected)
        changed_files: list[str] = []
        if changes:
            validation = validate_recipe(parse_recipe(patched))
            if validation:
                raise ValueError("source_operation_invalid_result:" + ",".join(validation))
            rendered = _replace_recipe(current, patched)
            temporary = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(rendered, encoding="utf-8")
                temporary.replace(config_path)
            finally:
                temporary.unlink(missing_ok=True)
            changed_files.append(preview["config_ref"])
        counts = discovery.get("counts") or {}
        status = "inventory_applied" if changes else "inventory_no_change" if not actionable else "inventory_reviewed"
        operation_id = "sop-" + uuid.uuid4().hex[:12]
        receipt = {
            "schema_version": SOURCE_OPERATION_SCHEMA_VERSION,
            "operation_id": operation_id,
            "recorded_at": _now(),
            "source_id": source_id,
            "stream_id": "__source__",
            "scope": "source",
            "preview_token": preview_token,
            "config_ref": preview["config_ref"],
            "raw_path": "",
            "raw_sha256": discovery.get("fingerprint") or "",
            "argv": preview.get("execution", {}).get("argv") or [],
            "returncode": 0,
            "stdout": "",
            "stderr": preview.get("execution", {}).get("stderr") or "",
            "status": status,
            "changes": changes,
            "discovery": discovery,
            "selected_external_ids": sorted(selected),
            "summary": {
                "new": int(counts.get("new") or 0),
                "changed": int(counts.get("changed") or 0),
                "enriched": int(counts.get("enriched") or 0),
                "unchanged": int(counts.get("unchanged") or 0),
                "applied": len(changes),
            },
        }
        receipt_dir = WikiPaths(root, config).derived_root / "source-operations"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"{operation_id}.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "ok": True,
            **receipt,
            "receipt_path": str(receipt_path.relative_to(root)),
            "changed_files": changed_files,
            "source": _source(root, config, source_id),
        }

    raw_file = _safe_raw_path(root, config, raw_path)
    _, current_sha = _inventory_raw_path(root, raw_file)
    if current_sha != preview["raw_inventory"]["local_raw"]["sha256"]:
        raise ValueError("source_operation_preview_stale")
    argv = list(preview["execution"]["argv"])
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "") + "\nsource refresh timed out"
        returncode = None
    else:
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
    redact = lambda value: SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)[:200_000]
    operation_id = "sop-" + uuid.uuid4().hex[:12]
    receipt = {
        "schema_version": SOURCE_OPERATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "recorded_at": _now(),
        "source_id": source_id,
        "stream_id": stream_id,
        "scope": "source",
        "preview_token": preview_token,
        "config_ref": preview["config_ref"],
        "raw_path": preview["raw_path"],
        "raw_sha256": preview["raw_inventory"]["local_raw"]["sha256"],
        "argv": argv,
        "returncode": returncode,
        "stdout": redact(stdout),
        "stderr": redact(stderr),
        "status": "script_complete" if returncode == 0 else "script_failed",
        "changes": [],
    }
    receipt_dir = WikiPaths(root, config).derived_root / "source-operations"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{operation_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {"ok": returncode == 0, **receipt, "receipt_path": str(receipt_path.relative_to(root))}
