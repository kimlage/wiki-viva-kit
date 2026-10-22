from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import re
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values as _list_values
from wiki_core.frontmatter import parse_frontmatter_flat as parse_frontmatter
from wiki_core.paths import WikiPaths


ACCESS_SCHEMA = "wiki_source_access.v1"
_ACCESS_FIELDS = {"schema_version", "expected_identity", "coordinator", "executor", "requested_scopes"}


def _unsafe_access_label(value: str) -> bool:
    # These are short identities/pointers, never a login URL or callback blob.
    return bool(re.search(r"://|[?&#=]|\bbearer\s+", value, re.I))


def source_access_metadata(value: Any) -> dict[str, Any]:
    """Consumer-owned declarations, never observed permissions or credentials."""
    if value is None or value == {}:
        return {}
    if (not isinstance(value, dict) or not _ACCESS_FIELDS.issubset(value)
            or set(value) - _ACCESS_FIELDS - {"execution", "connection"}
            or value.get("schema_version") != ACCESS_SCHEMA):
        raise ValueError("source_access_metadata_invalid")
    native_session = bool(value.get("connection")) or isinstance(value.get("execution"), dict) and value["execution"].get("method") == "native_session"
    for key in ("expected_identity", "coordinator", "executor"):
        empty_identity = key == "expected_identity" and native_session
        if not isinstance(value[key], str) or (not value[key].strip() and not empty_identity) or len(value[key]) > 240 or any(ord(c) < 32 for c in value[key]) or _unsafe_access_label(value[key]):
            raise ValueError("source_access_metadata_invalid")
    scopes = value["requested_scopes"]
    if not isinstance(scopes, list) or len(scopes) > 32 or any(not isinstance(s, str) or not re.fullmatch(r"[\w:/.-]{1,240}", s) for s in scopes) or len(set(scopes)) != len(scopes):
        raise ValueError("source_access_metadata_invalid")
    from wiki_core.detectors import scan_text
    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if re.search(r"\bbearer\s+\S+", serialized, re.I) or any(f.category == "secret" for f in scan_text(serialized)):
        raise ValueError("source_access_metadata_invalid")
    if "execution" in value:
        execution = value["execution"]
        keys = {"connection_id", "profile", "target_profile", "method", "stored_session_id"}
        account_keys = {"provider_id", "account_id", "account_alias"}
        if (not isinstance(execution, dict) or set(execution) not in (keys, keys | account_keys)
                or execution.get("method") != "native_session"
                or any(not isinstance(execution[k], str) or len(execution[k]) > 240
                       or any(ord(c) < 32 for c in execution[k]) or _unsafe_access_label(execution[k]) for k in execution)
                or any(not execution[k].strip() for k in ("connection_id", "profile", "target_profile", "stored_session_id"))
                or not re.fullmatch(r"[\w-]{1,160}", execution["stored_session_id"])):
            raise ValueError("source_access_execution_invalid")
        if account_keys.issubset(execution) and (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,159}", execution["provider_id"]) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", execution["account_alias"]) or not re.fullmatch(r"[\w-]{1,160}", execution["account_id"])):
            raise ValueError("source_access_execution_invalid")
    if "connection" in value:
        connection = value["connection"]
        keys = {"connection_id", "profile", "target_profile"}
        account_keys = {"provider_id", "account_id", "account_alias"}
        if (not isinstance(connection, dict) or set(connection) not in (keys, keys | account_keys)
                or any(not isinstance(v, str) or not v.strip() or len(v) > 240
                       or any(ord(c) < 32 for c in v) or _unsafe_access_label(v) for v in connection.values())):
            raise ValueError("source_access_connection_invalid")
        if account_keys.issubset(connection) and (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,159}", connection["provider_id"]) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", connection["account_alias"]) or not re.fullmatch(r"[\w-]{1,160}", connection["account_id"])):
            raise ValueError("source_access_connection_invalid")
        legacy = value.get("execution")
        if legacy and (any(connection[k] != legacy[k] for k in keys)
                       or account_keys.issubset(legacy) and account_keys.issubset(connection)
                       and any(connection[k] != legacy[k] for k in account_keys)):
            raise ValueError("source_access_connection_owner_conflict")
    return {**value, "requested_scopes": list(scopes)}


def source_access_subject(source: dict[str, Any]) -> dict[str, Any]:
    """Bind observations to the exact declared source/account/executor/scope."""
    return {"source_id": source["source_id"], "context": source["context"],
            "platform": source["platform"], "locator": source["locator"],
            "auth": source.get("auth"), "access": source.get("access_policy") or {}}


def project_source_access(source: dict[str, Any], observation: Any = None, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Pure projection of an allowlisted adapter report. No login, grant or I/O.

    The caller must obtain observations from the existing trusted refresh
    adapter, not a browser POST or authored recipe. Missing evidence is unknown.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    policy = source_access_metadata(source.get("access_policy"))
    subject = source_access_subject(source)
    binding = hashlib.sha256(json.dumps(subject, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = {"schema_version": ACCESS_SCHEMA, "binding_sha256": binding,
              "status": "configured" if policy else "not_configured", "verified": False,
              "expected_identity": policy.get("expected_identity", ""), "confirmed_identity": "",
              "coordinator": policy.get("coordinator", ""), "executor": policy.get("executor", ""),
              "requested_scopes": policy.get("requested_scopes", []), "granted_scopes": [],
              "checked_at": "", "valid_until": "", "evidence_ref": "", "error_code": "",
              "execution_ready": False, "business_authority": "unknown"}
    if observation is None:
        return result
    if policy.get("execution") or policy.get("connection"):
        return {**result, "status": "execution_unknown", "error_code": "native_tool_evidence_required"}
    allowed = {"schema_version", "binding_sha256", "outcome", "confirmed_identity", "granted_scopes", "checked_at", "valid_until", "evidence_ref", "error_code"}
    if not isinstance(observation, dict) or set(observation) != allowed or observation.get("schema_version") != ACCESS_SCHEMA:
        return {**result, "status": "technical_blocked", "error_code": "invalid_probe"}
    # Never reflect arbitrary adapter output or credential material into the UI.
    from wiki_core.detectors import scan_text
    try:
        serialized = json.dumps(observation, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        return {**result, "status": "technical_blocked", "error_code": "invalid_probe"}
    if re.search(r"\bbearer\s+\S+", serialized, re.I) or any(f.category == "secret" for f in scan_text(serialized)):
        return {**result, "status": "technical_blocked", "error_code": "unsafe_probe"}
    for key in ("binding_sha256", "outcome", "confirmed_identity", "checked_at", "valid_until", "evidence_ref", "error_code"):
        if not isinstance(observation[key], str) or len(observation[key]) > 240 or any(ord(c) < 32 for c in observation[key]):
            return {**result, "status": "technical_blocked", "error_code": "invalid_probe"}
        if _unsafe_access_label(observation[key]):
            return {**result, "status": "technical_blocked", "error_code": "unsafe_probe"}
    if observation["binding_sha256"] != binding:
        return {**result, "status": "identity_mismatch", "error_code": "probe_subject_mismatch"}
    if observation["evidence_ref"] and (not re.fullmatch(r"[\w./:-]{1,240}", observation["evidence_ref"]) or "://" in observation["evidence_ref"]):
        return {**result, "status": "technical_blocked", "error_code": "invalid_evidence_ref"}
    scopes = observation["granted_scopes"]
    if not isinstance(scopes, list) or len(scopes) > 32 or any(not isinstance(s, str) or not re.fullmatch(r"[\w:/.-]{1,240}", s) for s in scopes) or len(set(scopes)) != len(scopes):
        return {**result, "status": "technical_blocked", "error_code": "invalid_probe"}
    outcome = observation["outcome"]
    if outcome not in {"verified", "awaiting_auth", "awaiting_approval", "authority_blocked", "technical_blocked", "execution_unknown", "revoked",
                        "wrong_account", "executor_unavailable", "session_expired", "authorization_missing"}:
        return {**result, "status": "technical_blocked", "error_code": "invalid_probe"}
    try:
        checked = dt.datetime.fromisoformat(observation["checked_at"].replace("Z", "+00:00"))
        expiry = dt.datetime.fromisoformat(observation["valid_until"].replace("Z", "+00:00"))
        if checked.tzinfo is None or expiry.tzinfo is None or checked > now or expiry <= checked:
            raise ValueError()
    except (ValueError, TypeError):
        return {**result, "status": "technical_blocked", "error_code": "invalid_probe_time"}
    result.update({key: observation[key] for key in ("confirmed_identity", "granted_scopes", "checked_at", "valid_until", "evidence_ref")})
    result["error_code"] = observation["error_code"] if re.fullmatch(r"[a-z0-9_:-]{0,100}", observation["error_code"]) else "adapter_error"
    result["status"] = outcome
    if expiry <= now:
        result.update(status="unknown", error_code="probe_expired")
    elif outcome == "verified":
        if not policy or observation["confirmed_identity"] != policy["expected_identity"]:
            result.update(status="identity_mismatch", error_code="unexpected_account")
        elif not set(policy["requested_scopes"]).issubset(scopes):
            result.update(status="authority_blocked", error_code="required_scope_missing")
        elif not re.fullmatch(r"[\w./:-]{1,240}", observation["evidence_ref"]) or "://" in observation["evidence_ref"]:
            result.update(status="technical_blocked", error_code="probe_evidence_missing")
        else:
            result["verified"] = True
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _repo_path(root: Path, source: str) -> Path | None:
    path = Path(source)
    if not path.is_absolute():
        path = root / source
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _read_config_page(path: Path, paths: WikiPaths) -> dict[str, Any] | None:
    if not path.exists():
        return None
    values = parse_frontmatter(path)
    if values.get("page_type") != "source_config":
        return None
    return {
        "path": paths.rel(path),
        "page_id": str(values.get("page_id") or ""),
        "perspectives_required": _list_values(values.get("perspectives_required")),
        "perspectives_optional": _list_values(values.get("perspectives_optional")),
        "perspectives_skip_with_reason": _list_values(values.get("perspectives_skip_with_reason")),
        "input_channel_ref": str(values.get("input_channel_ref") or "").strip(),
        "process_refs": _list_values(values.get("process_refs")),
        "target_pages": _list_values(values.get("target_pages")),
        "quadrants": _list_values(values.get("quadrants")),
    }


def find_source_config(root: Path, config: WikiConfig, source: str) -> dict[str, Any] | None:
    """Return the source_config page that governs a repo-local source page.

    The preferred link is `config_ref` on the source page. The fallback scans
    `sources/config/*.md` for a matching `source_refs` entry. Raw files and URLs
    have no source page identity, so they return None.
    """

    paths = WikiPaths(root, config)
    source_path = _repo_path(root, source)
    if source_path is None or not source_path.exists() or source_path.suffix.lower() != ".md":
        return None

    values = parse_frontmatter(source_path)
    source_keys = {key for key in (str(values.get("page_id") or ""), paths.rel(source_path)) if key}

    config_ref = str(values.get("config_ref") or "").strip()
    if config_ref:
        config_path = _repo_path(root, config_ref)
        if config_path is not None:
            direct = _read_config_page(config_path, paths)
            if direct is not None:
                return direct

    config_dir = paths.sources_dir / "config"
    if not config_dir.exists():
        return None
    for path in sorted(config_dir.rglob("*.md")):
        values = parse_frontmatter(path)
        if values.get("page_type") != "source_config":
            continue
        if source_keys & set(_list_values(values.get("source_refs"))):
            return _read_config_page(path, paths)
    return None


def merge_perspectives(
    source_config: dict[str, Any] | None,
    *,
    required: list[str],
    optional: list[str],
    root_required: list[str] | None = None,
    root_optional: list[str] | None = None,
    channel_required: list[str] | None = None,
    channel_optional: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    root_required = root_required or []
    root_optional = root_optional or []
    channel_required = channel_required or []
    channel_optional = channel_optional or []
    skipped = set(source_config.get("perspectives_skip_with_reason") or []) if source_config else set()
    merged_required = _dedupe(
        [
            item
            for item in (
                list(root_required)
                + list(channel_required)
                + list(source_config.get("perspectives_required") or [] if source_config else [])
                + list(required)
            )
            if item not in skipped
        ]
    )
    merged_optional = _dedupe(
        [
            value
            for value in (
                list(root_optional)
                + list(channel_optional)
                + list(source_config.get("perspectives_optional") or [] if source_config else [])
                + list(optional)
            )
            if value not in set(merged_required) and value not in skipped
        ]
    )
    return merged_required, merged_optional
