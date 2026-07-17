from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

HARNESS_VERSION = "wiki_performance_harness.v1"
PLAN_SCHEMA_VERSION = "wiki_performance_plan.v1"
RECEIPT_SCHEMA_VERSION = "wiki_performance_receipt.v1"
REPORT_SCHEMA_VERSION = "wiki_performance_report.v1"
STATE_SCHEMA_VERSION = "wiki_performance_state.v1"


class PerformanceContractError(ValueError):
    """Raised when evidence cannot be trusted or resumed safely."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformanceContractError(f"unreadable JSON evidence: {path}") from exc


def require_fields(
    payload: Mapping[str, Any],
    *,
    schema: str,
    fields: tuple[str, ...],
) -> None:
    if payload.get("schema_version") != schema:
        raise PerformanceContractError(
            f"schema mismatch: expected {schema}, got {payload.get('schema_version')!r}"
        )
    missing = [field for field in fields if field not in payload]
    if missing:
        raise PerformanceContractError(f"missing required fields: {', '.join(missing)}")


def validate_plan(payload: Mapping[str, Any]) -> None:
    require_fields(
        payload,
        schema=PLAN_SCHEMA_VERSION,
        fields=(
            "harness_version",
            "created_at",
            "source_subject",
            "profile",
            "fixture",
            "config_sha256",
            "toolchain",
            "commands",
            "command_registry_sha256",
            "measurement_policy",
            "heavy_authorization",
            "plan_sha256",
        ),
    )
    expected = sha256_value({k: v for k, v in payload.items() if k != "plan_sha256"})
    if payload.get("plan_sha256") != expected:
        raise PerformanceContractError("plan_sha256 mismatch")
    if payload.get("command_registry_sha256") != sha256_value(payload.get("commands")):
        raise PerformanceContractError("command_registry_sha256 mismatch")


def validate_receipt(payload: Mapping[str, Any]) -> None:
    require_fields(
        payload,
        schema=RECEIPT_SCHEMA_VERSION,
        fields=(
            "harness_version",
            "plan_sha256",
            "source_subject_sha256",
            "fixture_sha256",
            "toolchain_sha256",
            "started_at",
            "completed_at",
            "steps",
            "outputs",
            "receipt_sha256",
        ),
    )
    expected = sha256_value({k: v for k, v in payload.items() if k != "receipt_sha256"})
    if payload.get("receipt_sha256") != expected:
        raise PerformanceContractError("receipt_sha256 mismatch")
