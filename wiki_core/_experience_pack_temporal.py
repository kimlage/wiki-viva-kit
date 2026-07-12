"""Closed declarative temporal adapters for installed experience packs.

Packs contribute data only.  This trusted core validates a deliberately small
field-mapping vocabulary, projects only the named fields into the snapshot and
later lets ``wiki_core.web.temporal`` compile canonical events.  No expression,
import, callable or executable path is accepted by this contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

from wiki_core._experience_pack_common import (
    TEMPORAL_PROFILES_SCHEMA_VERSION,
    PackError,
    _CAPABILITY_RE,
    _SHA256_RE,
    _assert_no_symlink_chain,
    _contained,
    _load_yaml,
    _safe_relative,
    _sha256_bytes,
    _sha256_json,
)
from wiki_core.temporal import TEMPORAL_DATE_FIELDS, TEMPORAL_LANE_IDS

PACK_TEMPORAL_ADAPTER_VERSION = "wiki_experience_pack_temporal_adapter.v1"

_EVENT_KIND_RE = re.compile(
    r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,5}"
)
_STATE_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PROVENANCE_POLICIES = frozenset({"optional", "required"})
_CONFIDENCE = frozenset({"confirmed", "inferred", "uncertain"})
_BASE_PAGE_FIELDS = frozenset(
    {
        "page_id",
        "page_type",
        "title",
        "visibility",
        "context",
        "updated_at",
        "stale_after_days",
        "source_ref",
        "source_refs",
        "evidence_refs",
        "temporal_precision",
    }
)


def _identifier_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PackError("temporal_adapter_identifier_list_required", label)
    output: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not _CAPABILITY_RE.fullmatch(item)
            or item in output
        ):
            raise PackError("temporal_adapter_identifier_invalid", label)
        output.append(item)
    return output


def _field_map(value: Any, *, label: str, keys: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise PackError("temporal_adapter_field_map_required", label)
    output: dict[str, str] = {}
    for raw_key, raw_field in sorted(value.items()):
        key = str(raw_key)
        field = str(raw_field)
        valid_key = key in TEMPORAL_DATE_FIELDS if keys == "time" else bool(
            _STATE_KEY_RE.fullmatch(key)
        )
        if (
            not valid_key
            or not _CAPABILITY_RE.fullmatch(field)
            or key in output
        ):
            raise PackError("temporal_adapter_field_map_invalid", label)
        output[key] = field
    return output


def normalize_temporal_document(
    document: Mapping[str, Any],
    *,
    pack_id: str,
    declared_profiles: Sequence[str],
    profile_slots: Mapping[str, str],
    declared_page_types: Sequence[str],
    page_type_fields: Mapping[str, Collection[str]],
) -> list[dict[str, Any]]:
    """Validate v2 profiles plus adapters and return canonical adapter rows."""

    if (
        set(document) != {"schema_version", "pack", "profiles", "adapters"}
        or document.get("schema_version") != TEMPORAL_PROFILES_SCHEMA_VERSION
        or document.get("pack") != pack_id
        or not isinstance(document.get("profiles"), Mapping)
        or not isinstance(document.get("adapters"), Mapping)
    ):
        raise PackError("temporal_artifact_contract_invalid", pack_id)

    profiles = document["profiles"]
    if set(profiles) != set(declared_profiles):
        raise PackError("temporal_artifact_capability_mismatch", pack_id)
    for profile_id, record in sorted(profiles.items()):
        if not isinstance(record, Mapping) or not {
            "slot",
            "event_times",
            "lanes",
            "precision_policy",
        }.issubset(record) or not set(record).issubset(
            {
                "slot",
                "event_times",
                "lanes",
                "precision_policy",
                "horizon",
                "comparison",
            }
        ):
            raise PackError("temporal_artifact_record_invalid", str(profile_id))
        if record.get("slot") != profile_slots.get(str(profile_id)):
            raise PackError("temporal_artifact_slot_mismatch", str(profile_id))
        _identifier_list(
            record.get("event_times"), label=f"temporal:{profile_id}:event_times"
        )
        _identifier_list(record.get("lanes"), label=f"temporal:{profile_id}:lanes")
        if record.get("precision_policy") != "preserve_unknown":
            raise PackError("temporal_precision_policy_invalid", str(profile_id))
        for optional in ("horizon", "comparison"):
            if optional in record and (
                not isinstance(record[optional], str)
                or not _CAPABILITY_RE.fullmatch(record[optional])
            ):
                raise PackError(
                    "temporal_artifact_identifier_invalid", str(profile_id)
                )

    adapters = document["adapters"]
    if not adapters:
        raise PackError("temporal_adapters_required", pack_id)
    page_types = set(declared_page_types)
    normalized: list[dict[str, Any]] = []
    event_kinds: set[str] = set()
    for adapter_id, record in sorted(adapters.items()):
        if (
            not isinstance(adapter_id, str)
            or not adapter_id.startswith(f"{pack_id}.")
            or not _CAPABILITY_RE.fullmatch(adapter_id)
            or not isinstance(record, Mapping)
            or set(record)
            != {
                "schema_version",
                "page_type",
                "event_kind",
                "lane",
                "time",
                "required_times",
                "state",
                "provenance",
                "confidence",
            }
            or record.get("schema_version") != PACK_TEMPORAL_ADAPTER_VERSION
        ):
            raise PackError("temporal_adapter_record_invalid", str(adapter_id))
        page_type = str(record.get("page_type") or "")
        event_kind = str(record.get("event_kind") or "")
        lane = str(record.get("lane") or "")
        if page_type not in page_types:
            raise PackError("temporal_adapter_page_type_unknown", str(adapter_id))
        inventory = _BASE_PAGE_FIELDS | frozenset(
            str(field) for field in page_type_fields.get(page_type, ())
        )
        if (
            not event_kind.startswith(f"{pack_id}.")
            or not _EVENT_KIND_RE.fullmatch(event_kind)
            or event_kind in event_kinds
        ):
            raise PackError("temporal_adapter_event_kind_invalid", str(adapter_id))
        event_kinds.add(event_kind)
        if lane not in TEMPORAL_LANE_IDS:
            raise PackError("temporal_adapter_lane_invalid", str(adapter_id))
        time = _field_map(record.get("time"), label=str(adapter_id), keys="time")
        if not time:
            raise PackError("temporal_adapter_time_required", str(adapter_id))
        if not set(time.values()).issubset(inventory):
            raise PackError("temporal_adapter_source_field_unknown", str(adapter_id))
        required_times = _identifier_list(
            record.get("required_times"), label=f"{adapter_id}:required_times"
        )
        if not set(required_times).issubset(time):
            raise PackError("temporal_adapter_required_time_unknown", str(adapter_id))
        state = record.get("state")
        if not isinstance(state, Mapping) or set(state) != {"before", "after"}:
            raise PackError("temporal_adapter_state_invalid", str(adapter_id))
        before = _field_map(
            state.get("before"), label=f"{adapter_id}:before", keys="state"
        )
        after = _field_map(
            state.get("after"), label=f"{adapter_id}:after", keys="state"
        )
        if not (set(before.values()) | set(after.values())).issubset(inventory):
            raise PackError("temporal_adapter_source_field_unknown", str(adapter_id))
        provenance = record.get("provenance")
        if (
            not isinstance(provenance, Mapping)
            or set(provenance) != {"source_refs", "evidence_refs"}
        ):
            raise PackError("temporal_adapter_provenance_invalid", str(adapter_id))
        normalized_provenance: dict[str, dict[str, Any]] = {}
        for provenance_kind in ("source_refs", "evidence_refs"):
            spec = provenance.get(provenance_kind)
            if (
                not isinstance(spec, Mapping)
                or set(spec) != {"policy", "fields"}
                or spec.get("policy") not in _PROVENANCE_POLICIES
                or not isinstance(spec.get("fields"), list)
                or not spec["fields"]
            ):
                raise PackError(
                    "temporal_adapter_provenance_invalid", str(adapter_id)
                )
            provenance_fields = _identifier_list(
                spec["fields"], label=f"{adapter_id}:{provenance_kind}"
            )
            if not set(provenance_fields).issubset(inventory):
                raise PackError(
                    "temporal_adapter_provenance_field_unknown", str(adapter_id)
                )
            normalized_provenance[provenance_kind] = {
                "policy": str(spec["policy"]),
                "fields": provenance_fields,
            }
        confidence = str(record.get("confidence") or "")
        if confidence not in _CONFIDENCE:
            raise PackError("temporal_adapter_confidence_invalid", str(adapter_id))
        normalized.append(
            {
                "pack": pack_id,
                "adapter_id": adapter_id,
                "page_type": page_type,
                "event_kind": event_kind,
                "lane": lane,
                "time": time,
                "required_times": required_times,
                "state": {"before": before, "after": after},
                "provenance": normalized_provenance,
                "confidence": confidence,
            }
        )
    return normalized


def temporal_adapter_projection(
    adapters: Sequence[Mapping[str, Any]],
) -> dict[str, frozenset[str]]:
    """Return the exact frontmatter fields the snapshot may project per type."""

    fields: dict[str, set[str]] = {}
    for adapter in adapters:
        page_type = str(adapter["page_type"])
        selected = fields.setdefault(page_type, set())
        selected.update(str(value) for value in adapter["time"].values())
        for side in ("before", "after"):
            selected.update(
                str(value) for value in adapter["state"][side].values()
            )
        for provenance_kind in ("source_refs", "evidence_refs"):
            selected.update(
                str(value)
                for value in adapter["provenance"][provenance_kind]["fields"]
            )
    return {key: frozenset(sorted(value)) for key, value in sorted(fields.items())}


def load_active_temporal_adapters(root: Path) -> list[dict[str, Any]]:
    """Load adapter rows only from hash-verified active installed bundles."""

    # Local imports avoid a module cycle: source validation uses the pure
    # normalizer above, while installed-state loading depends on lock parsing.
    from wiki_core._experience_pack_state import load_lock
    from wiki_core._experience_pack_validation import _pack_tree

    lock = load_lock(root)
    adapters: list[dict[str, Any]] = []
    for pack_id, entry in sorted(lock["packs"].items()):
        if entry.get("status") != "active":
            continue
        bundle = _contained(root, entry["installed_path"], label="installed pack")
        _assert_no_symlink_chain(root, bundle, label="installed pack")
        files = _pack_tree(bundle)
        file_rows = [file.__dict__ for file in files]
        if file_rows != entry["files"] or _sha256_json(file_rows) != entry["tree_sha256"]:
            raise PackError("installed_bundle_drift", pack_id)
        inventory = {row["path"]: row for row in file_rows}
        manifest_path = bundle / "pack.yaml"
        manifest_raw = manifest_path.read_bytes()
        if (
            _sha256_bytes(manifest_raw) != entry["manifest_sha256"]
            or inventory.get("pack.yaml", {}).get("sha256")
            != entry["manifest_sha256"]
        ):
            raise PackError("installed_manifest_drift", pack_id)
        manifest = _load_yaml(manifest_path, label=f"installed manifest:{pack_id}")
        temporal_relative = _safe_relative(
            (manifest.get("artifacts") or {}).get("temporal"),
            label=f"installed temporal:{pack_id}",
        )
        page_types_relative = _safe_relative(
            (manifest.get("artifacts") or {}).get("page_types"),
            label=f"installed page types:{pack_id}",
        )
        for relative in (temporal_relative, page_types_relative):
            path = _contained(bundle, relative, label=f"installed artifact:{pack_id}")
            raw = path.read_bytes()
            row = inventory.get(relative)
            if (
                not isinstance(row, Mapping)
                or not _SHA256_RE.fullmatch(str(row.get("sha256") or ""))
                or _sha256_bytes(raw) != row["sha256"]
            ):
                raise PackError("installed_bundle_drift", pack_id)
        temporal = _load_yaml(
            bundle / temporal_relative, label=f"installed temporal:{pack_id}"
        )
        page_types_document = _load_yaml(
            bundle / page_types_relative, label=f"installed page types:{pack_id}"
        )
        page_types = page_types_document.get("page_types")
        if not isinstance(page_types, Mapping):
            raise PackError("temporal_adapter_page_types_invalid", pack_id)
        profile_slots = {
            str(row["contribution"]): str(row["slot"])
            for row in entry["slots"]["timelines"]
        }
        adapters.extend(
            normalize_temporal_document(
                temporal,
                pack_id=pack_id,
                declared_profiles=entry["capabilities"]["temporal_profiles"],
                profile_slots=profile_slots,
                declared_page_types=entry["capabilities"]["page_types"],
                page_type_fields={
                    str(page_type): tuple(record.get("fields") or ())
                    for page_type, record in page_types.items()
                    if isinstance(record, Mapping)
                },
            )
        )
    return sorted(adapters, key=lambda row: (row["pack"], row["adapter_id"]))


__all__ = [
    "PACK_TEMPORAL_ADAPTER_VERSION",
    "load_active_temporal_adapters",
    "normalize_temporal_document",
    "temporal_adapter_projection",
]
