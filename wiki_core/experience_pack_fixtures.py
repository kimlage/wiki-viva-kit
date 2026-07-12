"""Trusted compiler for declarative dense and intentional-failure pack fixtures."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from wiki_core._experience_pack_common import (
    PackError,
    _CAPABILITY_RE,
    _contained,
    _load_yaml,
    _safe_relative,
)
from wiki_core._experience_pack_temporal import normalize_temporal_document
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.output_safety import (
    contained_output_path,
    prepare_managed_output_directory,
)

FIXTURE_SCHEMA_VERSION = "wiki_experience_pack_fixture.v1"
FIXTURE_COMPILER_SCHEMA_VERSION = "wiki_experience_pack_fixture_compiler.v1"
FIXTURE_OUTPUT_KIND = "experience_pack_fixture"

_COMPILER_FIELDS = {
    "schema_version",
    "mode",
    "seed",
    "reference_date",
    "base_fixture",
    "type_counts",
    "mutations",
    "checks",
    "expected_diagnostic_codes",
}
_MUTATION_FIELDS = {
    "clone_page": {"operation", "page_id", "new_page_id"},
    "remove_page": {"operation", "page_id"},
    "set_field": {"operation", "page_id", "field", "value"},
}
_CHECK_FIELDS = {
    "reference_integrity": {"kind", "fields", "code"},
    "duplicate_key": {"kind", "page_type", "fields", "code"},
    "overdue_state": {
        "kind",
        "page_type",
        "state_field",
        "active_values",
        "due_field",
        "code",
    },
    "public_boundary": {"kind", "code"},
    "conflicting_values": {
        "kind",
        "page_type",
        "key_fields",
        "value_field",
        "code",
    },
}


def _render(values: Mapping[str, Any], body: str) -> str:
    return (
        "---\n"
        + yaml.safe_dump(dict(values), sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + body.strip()
        + "\n"
    )


def _safe_scalar(value: Any, *, label: str) -> Any:
    if (
        value is None
        or isinstance(value, (bool, int, str))
        or (isinstance(value, float) and math.isfinite(value))
    ):
        return value
    raise PackError("fixture_mutation_value_invalid", label)


def _load_pages(path: Path) -> list[dict[str, Any]]:
    pages_dir = path / "pages"
    if not pages_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for page_path in sorted(pages_dir.glob("*.md")):
        if page_path.is_symlink():
            raise PackError("symlink_blocked", page_path.name)
        values, body = parse_frontmatter(page_path)
        page_id = str(values.get("page_id") or "")
        if not page_id or not _CAPABILITY_RE.fullmatch(page_id):
            raise PackError("fixture_page_id_required", page_path.name)
        records.append({"values": dict(values), "body": body})
    ids = [str(record["values"]["page_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise PackError("fixture_page_id_duplicate")
    return records


def _adapter_rows(source: Any) -> list[dict[str, Any]]:
    temporal = _load_yaml(
        source.path / source.manifest["artifacts"]["temporal"],
        label="fixture temporal adapter",
    )
    page_types_document = _load_yaml(
        source.path / source.manifest["artifacts"]["page_types"],
        label="fixture page types",
    )
    page_types = page_types_document.get("page_types")
    if not isinstance(page_types, Mapping):
        raise PackError("fixture_page_types_invalid")
    slots = {
        str(row["contribution"]): str(row["slot"])
        for row in source.manifest["slots"]["timelines"]
    }
    return normalize_temporal_document(
        temporal,
        pack_id=source.pack_id,
        declared_profiles=source.manifest["capabilities"]["temporal_profiles"],
        profile_slots=slots,
        declared_page_types=source.manifest["capabilities"]["page_types"],
        page_type_fields={
            str(page_type): tuple(record.get("fields") or ())
            for page_type, record in page_types.items()
            if isinstance(record, Mapping)
        },
    )


def _deterministic_time(field: str, index: int) -> str:
    month = (index % 12) + 1
    day = (index % 27) + 1
    if field == "period":
        return f"2026-{month:02d}"
    return f"2026-{month:02d}-{day:02d}"


def _generated_records(
    source: Any,
    type_counts: Mapping[str, Any],
    adapters: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    declared = set(source.manifest["capabilities"]["page_types"])
    if not type_counts or set(type_counts) - declared:
        raise PackError("fixture_generated_page_type_unknown", source.pack_id)
    adapter_by_type: dict[str, list[Mapping[str, Any]]] = {}
    for adapter in adapters:
        adapter_by_type.setdefault(str(adapter["page_type"]), []).append(adapter)
    page_types_document = _load_yaml(
        source.path / source.manifest["artifacts"]["page_types"],
        label="fixture page types",
    )
    page_types = page_types_document["page_types"]
    records: list[dict[str, Any]] = []
    for page_type, raw_count in sorted(type_counts.items()):
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or raw_count < 1
            or raw_count > 10_000
        ):
            raise PackError("fixture_generated_count_invalid", str(page_type))
        template_relative = _safe_relative(
            page_types[page_type]["template"], label=f"fixture template:{page_type}"
        )
        template_path = _contained(
            source.path, template_relative, label=f"fixture template:{page_type}"
        )
        template_values, template_body = parse_frontmatter(template_path)
        for index in range(1, raw_count + 1):
            values = dict(template_values)
            values.update(
                {
                    "page_id": f"fixture-{page_type.replace('_', '-')}-{index:04d}",
                    "title": f"Synthetic {page_type} {index:04d}",
                    "visibility": "public",
                    "context": "fixture",
                    "updated_at": "2026-07-09",
                    "stale_after_days": 3650,
                }
            )
            for adapter in adapter_by_type.get(str(page_type), []):
                for source_field in adapter["time"].values():
                    if values.get(source_field) in (None, ""):
                        values[str(source_field)] = _deterministic_time(
                            str(source_field), index
                        )
                if adapter["provenance"]["source_refs"]["policy"] == "required":
                    source_field = adapter["provenance"]["source_refs"]["fields"][0]
                    values[source_field] = (
                        "fixture-source"
                        if source_field == "source_ref"
                        else ["fixture-source"]
                    )
                if adapter["provenance"]["evidence_refs"]["policy"] == "required":
                    evidence_field = adapter["provenance"]["evidence_refs"]["fields"][0]
                    values[evidence_field] = ["fixture-evidence"]
            records.append({"values": values, "body": template_body})
    return records


def _normalize_common_refs(records: list[dict[str, Any]]) -> None:
    for record in records:
        values = record["values"]
        if values.get("source_ref") and not values.get("source_refs"):
            values["source_refs"] = [values["source_ref"]]
        evidence = list(values.get("evidence_refs") or [])
        for field in ("evidence_for", "evidence_against"):
            for ref in values.get(field) or []:
                if ref not in evidence:
                    evidence.append(ref)
        if evidence:
            values["evidence_refs"] = evidence


def _add_support_records(records: list[dict[str, Any]]) -> None:
    ids = {str(record["values"].get("page_id") or "") for record in records}
    referenced_ids = {
        str(ref)
        for record in records
        for field in ("source_refs", "evidence_refs")
        for ref in record["values"].get(field) or []
        if str(ref)
    }
    for source_id in sorted(referenced_ids - ids):
        if not _CAPABILITY_RE.fullmatch(source_id):
            raise PackError("fixture_reference_id_invalid", source_id)
        records.append(
            {
                "values": {
                    "page_id": source_id,
                    "page_type": "source",
                    "title": f"Synthetic provenance {source_id}",
                    "visibility": "public",
                    "context": "fixture",
                    "updated_at": "2026-07-09",
                    "stale_after_days": 3650,
                    "source_lifecycle_state": "ready",
                },
                "body": "# Synthetic provenance\n\nFixture-only source anchor.",
            }
        )


def _record_by_id(records: Sequence[dict[str, Any]], page_id: str) -> dict[str, Any]:
    matches = [record for record in records if record["values"].get("page_id") == page_id]
    if len(matches) != 1:
        raise PackError("fixture_mutation_page_not_unique", page_id)
    return matches[0]


def _apply_mutations(
    records: list[dict[str, Any]], mutations: Any
) -> None:
    if not isinstance(mutations, list) or not mutations:
        raise PackError("fixture_failure_mutations_required")
    for mutation in mutations:
        operation = str(mutation.get("operation") or "") if isinstance(mutation, Mapping) else ""
        if operation not in _MUTATION_FIELDS or set(mutation) != _MUTATION_FIELDS[operation]:
            raise PackError("fixture_mutation_contract_invalid", operation)
        page_id = str(mutation["page_id"])
        if operation == "clone_page":
            source = _record_by_id(records, page_id)
            clone = {
                "values": dict(source["values"]),
                "body": str(source["body"]),
            }
            clone["values"]["page_id"] = str(mutation["new_page_id"])
            records.append(clone)
        elif operation == "remove_page":
            target = _record_by_id(records, page_id)
            records.remove(target)
        elif operation == "set_field":
            target = _record_by_id(records, page_id)
            field = str(mutation["field"])
            if not _CAPABILITY_RE.fullmatch(field) or field in {
                "page_id",
                "page_type",
            }:
                raise PackError("fixture_mutation_field_invalid", field)
            target["values"][field] = _safe_scalar(
                mutation["value"], label=f"{page_id}:{field}"
            )


def _refs(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _check_diagnostics(
    records: Sequence[dict[str, Any]],
    checks: Any,
    *,
    reference_date: dt.date,
) -> list[str]:
    if not isinstance(checks, list) or not checks:
        raise PackError("fixture_checks_required")
    diagnostics: list[str] = []
    ids = {str(record["values"].get("page_id") or "") for record in records}
    for check in checks:
        kind = str(check.get("kind") or "") if isinstance(check, Mapping) else ""
        if kind not in _CHECK_FIELDS or set(check) != _CHECK_FIELDS[kind]:
            raise PackError("fixture_check_contract_invalid", kind)
        code = str(check["code"])
        if not _CAPABILITY_RE.fullmatch(code):
            raise PackError("fixture_diagnostic_code_invalid", kind)
        if kind == "reference_integrity":
            fields = [str(value) for value in check["fields"]]
            if any(not _CAPABILITY_RE.fullmatch(field) for field in fields):
                raise PackError("fixture_check_field_invalid", kind)
            if any(
                ref not in ids
                for record in records
                for field in fields
                for ref in _refs(record["values"].get(field))
            ):
                diagnostics.append(code)
        elif kind == "duplicate_key":
            page_type = str(check["page_type"])
            fields = [str(value) for value in check["fields"]]
            seen: set[tuple[str, ...]] = set()
            for record in records:
                values = record["values"]
                if values.get("page_type") != page_type:
                    continue
                key = tuple(str(values.get(field) or "") for field in fields)
                if all(key) and key in seen:
                    diagnostics.append(code)
                    break
                seen.add(key)
        elif kind == "overdue_state":
            for record in records:
                values = record["values"]
                if (
                    values.get("page_type") != check["page_type"]
                    or values.get(check["state_field"])
                    not in check["active_values"]
                ):
                    continue
                try:
                    due = dt.date.fromisoformat(str(values.get(check["due_field"])))
                except ValueError:
                    continue
                if due < reference_date:
                    diagnostics.append(code)
                    break
        elif kind == "public_boundary":
            if any(record["values"].get("visibility") != "public" for record in records):
                diagnostics.append(code)
        elif kind == "conflicting_values":
            groups: dict[tuple[str, ...], set[str]] = {}
            for record in records:
                values = record["values"]
                if values.get("page_type") != check["page_type"]:
                    continue
                key = tuple(
                    str(values.get(field) or "") for field in check["key_fields"]
                )
                if not all(key):
                    continue
                groups.setdefault(key, set()).add(
                    str(values.get(check["value_field"]) or "")
                )
            if any(len(values - {""}) > 1 for values in groups.values()):
                diagnostics.append(code)
    return sorted(set(diagnostics))


def _identifier_array(value: Any, *, label: str, empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not empty and not value):
        raise PackError("fixture_identifier_list_invalid", label)
    result = [str(item) for item in value]
    if (
        any(not _CAPABILITY_RE.fullmatch(item) for item in result)
        or len(result) != len(set(result))
    ):
        raise PackError("fixture_identifier_list_invalid", label)
    return result


def _validate_compiler(compiler: Any, *, mode: str) -> dict[str, Any]:
    if (
        not isinstance(compiler, Mapping)
        or set(compiler) != _COMPILER_FIELDS
        or compiler.get("schema_version") != FIXTURE_COMPILER_SCHEMA_VERSION
        or compiler.get("mode") != mode
        or isinstance(compiler.get("seed"), bool)
        or not isinstance(compiler.get("seed"), int)
        or compiler["seed"] < 0
    ):
        raise PackError("fixture_compiler_contract_invalid", mode)
    try:
        dt.date.fromisoformat(str(compiler["reference_date"]))
    except ValueError as exc:
        raise PackError("fixture_reference_date_invalid", mode) from exc
    expected = _identifier_array(
        compiler["expected_diagnostic_codes"],
        label="expected_diagnostic_codes",
        empty=True,
    )
    if expected != sorted(expected):
        raise PackError("fixture_expected_diagnostics_not_canonical", mode)
    if not isinstance(compiler["type_counts"], Mapping):
        raise PackError("fixture_type_counts_invalid", mode)
    for page_type, count in compiler["type_counts"].items():
        if (
            not isinstance(page_type, str)
            or not _CAPABILITY_RE.fullmatch(page_type)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            or count > 10_000
        ):
            raise PackError("fixture_type_counts_invalid", mode)
    if not isinstance(compiler["mutations"], list) or not isinstance(
        compiler["checks"], list
    ):
        raise PackError("fixture_compiler_lists_invalid", mode)
    for mutation in compiler["mutations"]:
        operation = (
            str(mutation.get("operation") or "")
            if isinstance(mutation, Mapping)
            else ""
        )
        if (
            operation not in _MUTATION_FIELDS
            or set(mutation) != _MUTATION_FIELDS[operation]
            or not _CAPABILITY_RE.fullmatch(str(mutation.get("page_id") or ""))
        ):
            raise PackError("fixture_mutation_contract_invalid", operation)
        if operation == "clone_page" and not _CAPABILITY_RE.fullmatch(
            str(mutation.get("new_page_id") or "")
        ):
            raise PackError("fixture_mutation_contract_invalid", operation)
        if operation == "set_field":
            field = str(mutation.get("field") or "")
            if not _CAPABILITY_RE.fullmatch(field) or field in {
                "page_id",
                "page_type",
            }:
                raise PackError("fixture_mutation_field_invalid", field)
            _safe_scalar(mutation.get("value"), label=field)
    for check in compiler["checks"]:
        kind = (
            str(check.get("kind") or "") if isinstance(check, Mapping) else ""
        )
        if kind not in _CHECK_FIELDS or set(check) != _CHECK_FIELDS[kind]:
            raise PackError("fixture_check_contract_invalid", kind)
        if not _CAPABILITY_RE.fullmatch(str(check.get("code") or "")):
            raise PackError("fixture_diagnostic_code_invalid", kind)
        for field_name in ("fields", "key_fields", "active_values"):
            if field_name in check:
                _identifier_array(check[field_name], label=f"{kind}:{field_name}")
        for field_name in (
            "page_type",
            "state_field",
            "due_field",
            "value_field",
        ):
            if field_name in check and not _CAPABILITY_RE.fullmatch(
                str(check[field_name])
            ):
                raise PackError("fixture_check_field_invalid", kind)
    if mode == "dense":
        if (
            compiler["base_fixture"] is not None
            or not compiler["type_counts"]
            or compiler["mutations"]
            or compiler["checks"]
            or expected
        ):
            raise PackError("fixture_dense_compiler_invalid")
    else:
        _safe_relative(compiler["base_fixture"], label="fixture base")
        if (
            compiler["type_counts"]
            or not compiler["mutations"]
            or not compiler["checks"]
            or not expected
        ):
            raise PackError("fixture_failure_compiler_invalid")
    return dict(compiler)


def validate_fixture_compiler_contract(scenario: Mapping[str, Any]) -> None:
    """Validate the closed compiler block without materializing its fixture."""

    expected_state = str(scenario.get("expected_state") or "")
    failure_code = str(scenario.get("failure_code") or "")
    requires_compiler = expected_state == "dense_ready" or bool(failure_code)
    if not requires_compiler:
        if "compiler" in scenario:
            raise PackError("fixture_compiler_not_allowed", expected_state)
        return
    mode = "dense" if expected_state == "dense_ready" else "failure"
    compiler = _validate_compiler(scenario.get("compiler"), mode=mode)
    if mode == "failure" and compiler["expected_diagnostic_codes"] != [
        failure_code
    ]:
        raise PackError("fixture_failure_code_mismatch", failure_code)


def _prepare_fixture_output(
    root: Path,
    target: Path,
    *,
    owner_id: str,
) -> Path:
    """Accept only an empty or owned child of the fixture-output namespace."""

    namespace = (root / ".wiki-viva/fixture-output").resolve()
    try:
        resolved = contained_output_path(root, target)
        relative = resolved.relative_to(namespace)
        if not relative.parts:
            raise ValueError("fixture output must be a dedicated child")
        return prepare_managed_output_directory(
            root,
            resolved,
            kind=FIXTURE_OUTPUT_KIND,
            repo_id=owner_id,
            clean=True,
        )
    except ValueError as exc:
        raise PackError("fixture_output_target_invalid") from exc


def compile_pack_fixture(
    root: Path,
    pack_id: str,
    fixture_relative: str,
    target: Path,
    *,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize one declared dense/failure scenario into ``target``."""

    # Keep the pure contract validator importable from source validation without
    # forming a module cycle through the public experience-packs facade.
    from wiki_core.experience_packs import resolve_pack

    source = resolve_pack(root, pack_id, registry_path=registry_path)
    relative = _safe_relative(fixture_relative, label="fixture")
    if relative not in source.manifest["fixtures"]:
        raise PackError("fixture_not_declared", relative)
    fixture = _contained(source.path, relative, label="fixture")
    scenario = _load_yaml(fixture / "scenario.yaml", label="fixture scenario")
    if (
        scenario.get("schema_version") != FIXTURE_SCHEMA_VERSION
        or scenario.get("public_synthetic") is not True
    ):
        raise PackError("public_fixture_contract_invalid", relative)
    validate_fixture_compiler_contract(scenario)
    mode = "dense" if scenario.get("expected_state") == "dense_ready" else "failure"
    compiler = _validate_compiler(scenario.get("compiler"), mode=mode)
    adapters = _adapter_rows(source)
    if mode == "dense":
        if compiler["base_fixture"] is not None or compiler["mutations"] or compiler["checks"]:
            raise PackError("fixture_dense_compiler_invalid")
        records = _generated_records(source, compiler["type_counts"], adapters)
    else:
        base_relative = _safe_relative(
            compiler["base_fixture"], label="fixture base"
        )
        if base_relative not in source.manifest["fixtures"]:
            raise PackError("fixture_base_not_declared", base_relative)
        records = _load_pages(source.path / base_relative)
        if not records:
            raise PackError("fixture_base_pages_required", base_relative)
        _normalize_common_refs(records)
        _add_support_records(records)
        _apply_mutations(records, compiler["mutations"])

    _normalize_common_refs(records)
    if mode == "dense":
        _add_support_records(records)
    diagnostics = _check_diagnostics(
        records,
        compiler["checks"] or [
            {"kind": "public_boundary", "code": "unexpected_private_fixture"}
        ],
        reference_date=dt.date.fromisoformat(str(compiler["reference_date"])),
    ) if mode == "failure" else []
    expected = sorted(set(str(code) for code in compiler["expected_diagnostic_codes"]))
    if diagnostics != expected:
        raise PackError(
            "fixture_diagnostic_mismatch",
            f"expected={','.join(expected)} actual={','.join(diagnostics)}",
        )

    target = _prepare_fixture_output(
        root,
        target,
        owner_id=f"{pack_id}:{relative}",
    )
    memories = target / "memories"
    memories.mkdir(parents=True)
    root_values = {
        "page_id": f"root-{pack_id}-fixture",
        "page_type": "root_entity",
        "title": f"{pack_id} fixture",
        "visibility": "public",
        "context": "fixture",
        "updated_at": "2026-07-09",
        "stale_after_days": 3650,
        "root_entity_type": "system",
    }
    _contained(target, "memories/index.md", label="fixture root page").write_text(
        _render(root_values, f"# {pack_id} fixture\n\nDeterministic public fixture."),
        encoding="utf-8",
    )
    for index, record in enumerate(
        sorted(records, key=lambda row: str(row["values"].get("page_id") or "")),
        start=1,
    ):
        page_id = str(record["values"].get("page_id") or "")
        if not page_id or not _CAPABILITY_RE.fullmatch(page_id):
            raise PackError("fixture_page_id_required")
        path = _contained(
            target,
            f"memories/fixture/{index:05d}-{page_id}.md",
            label="fixture page output",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _render(record["values"], str(record["body"])), encoding="utf-8"
        )
    type_counts: dict[str, int] = {}
    for record in records:
        page_type = str(record["values"].get("page_type") or "")
        type_counts[page_type] = type_counts.get(page_type, 0) + 1
    declared_counts = {
        str(key): int(value) for key, value in (compiler["type_counts"] or {}).items()
    }
    if mode == "dense" and any(
        type_counts.get(page_type) != count
        for page_type, count in declared_counts.items()
    ):
        raise PackError("fixture_materialized_count_mismatch")
    return {
        "schema_version": "wiki_experience_pack_fixture_report.v1",
        "pack": pack_id,
        "fixture": relative,
        "mode": mode,
        "page_count": len(records) + 1,
        "type_counts": dict(sorted(type_counts.items())),
        "diagnostic_codes": diagnostics,
    }


__all__ = [
    "FIXTURE_COMPILER_SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "compile_pack_fixture",
    "validate_fixture_compiler_contract",
]
