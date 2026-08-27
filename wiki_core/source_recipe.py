"""Source recipe — the executable ingestion manual, as data (not code).

A `source_config` page carries a fenced ```yaml``` block under a `recipe:` key
(schema `wiki_source_recipe.v1`): the platform + locator, the typed pipelines
with their cadence, and the CHANNELS/streams as first-class rows (id, selected,
filters, privacy, target pages). This is what an agent reads to ingest on
demand — Slack/Google Chat channels, WhatsApp export instructions, a Drive
folder — with NO credentials ever (structural metadata only).

Deterministic parse + validate. The intelligence stays in the agent; this module
only gives it a clean, checked contract to read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from wiki_core.detectors import scan_text
from wiki_core.source_schedule import SCHEDULE_MODES, SOURCE_KINDS, validate_schedule, validate_source_kind

SOURCE_RECIPE_SCHEMA_VERSION = "wiki_source_recipe.v1"
SOURCE_RECIPE_SAFETY_ERROR_CODE = "source_recipe_secret_detected"
SOURCE_RECIPE_STRUCTURE_ERROR_CODES = frozenset(
    {
        "source_recipe_auth_invalid",
        "source_recipe_auth_scopes_invalid",
        "source_recipe_ingest_invalid",
        "source_recipe_ingest_argv_invalid",
        "source_recipe_pipelines_invalid",
        "source_recipe_schedule_invalid",
        "source_recipe_stream_filters_invalid",
        "source_recipe_stream_target_pages_invalid",
        "source_recipe_streams_invalid",
    }
)

# Typed pipeline kinds (independently cadenced) — OpenMetadata pipelineType
# analogue, scoped to what this wiki actually runs.
PIPELINE_KINDS = frozenset({"metadata", "content", "deep_read", "usage"})
PLATFORMS = frozenset(
    {"slack", "gchat", "chatgpt", "whatsapp", "gmail", "drive", "google_photos", "web", "repo", "file", "calendar", "manual"}
)
PRIVACY_LEVELS = frozenset(
    {"private_self", "private_sensitive_allowed", "team_shared", "public_ok"}
)
# How the operator's credential is REACHED (a pointer, never the secret itself).
AUTH_METHODS = frozenset({"env", "keychain", "onepassword", "oauth_file", "mcp", "none"})
_RECIPE_BLOCK_RE = re.compile(r"```ya?ml\n(.*?)\n```", re.S)


@dataclass(frozen=True)
class AuthPointer:
    """A POINTER to where the operator's credential lives — never the secret. The
    agent reads the token from this location at ingest time; the wiki only records
    where to look. validate_recipe's secret scan rejects a pasted token."""

    method: str  # env | keychain | onepassword | oauth_file | mcp | none
    ref: str  # e.g. an env var name, a keychain item, an MCP server id
    scopes: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class SyncSchedule:
    mode: str  # on_demand | recurring | event_driven
    cadence_days: int = 0
    cron_hint: str = ""


@dataclass(frozen=True)
class Stream:
    id: str
    label: str
    selected: bool
    filters: dict[str, Any]
    privacy: str
    target_pages: tuple[str, ...]
    skip_reason: str
    cadence_days: int = 0  # per-stream override of the pipeline cadence (0 = inherit)


@dataclass(frozen=True)
class Pipeline:
    kind: str
    cadence_days: int


@dataclass(frozen=True)
class SourceRecipe:
    schema_version: str
    platform: str
    locator: str
    source_kind: str
    pipelines: tuple[Pipeline, ...]
    streams: tuple[Stream, ...]
    how_to_export: str
    ingest_argv: tuple[str, ...]
    mcp_hint: str
    auth: AuthPointer | None = None
    schedule: SyncSchedule | None = None
    structural_error_codes: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "locator": self.locator,
            "source_kind": self.source_kind,
            "pipelines": [{"kind": p.kind, "cadence_days": p.cadence_days} for p in self.pipelines],
            "streams": [
                {
                    "id": s.id,
                    "label": s.label,
                    "selected": s.selected,
                    "filters": s.filters,
                    "privacy": s.privacy,
                    "target_pages": list(s.target_pages),
                    "skip_reason": s.skip_reason,
                    "cadence_days": s.cadence_days,
                }
                for s in self.streams
            ],
            "how_to_export": self.how_to_export,
            "ingest": {"argv": list(self.ingest_argv), "mcp_hint": self.mcp_hint},
            "auth": (
                None
                if self.auth is None
                else {
                    "method": self.auth.method,
                    "ref": self.auth.ref,
                    "scopes": list(self.auth.scopes),
                    "note": self.auth.note,
                }
            ),
            "schedule": (
                None
                if self.schedule is None
                else {"mode": self.schedule.mode, "cadence_days": self.schedule.cadence_days, "cron_hint": self.schedule.cron_hint}
            ),
        }


def extract_recipe_mapping(text: str) -> dict[str, Any] | None:
    """Pull the `recipe:` mapping out of a source_config page. Accepts either a
    top-level `recipe:` key inside the first fenced YAML block, or a standalone
    fenced block whose root IS the recipe. Returns None when absent."""
    for block in _RECIPE_BLOCK_RE.findall(text):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("recipe"), dict):
            return data["recipe"]
        if str(data.get("schema_version") or "").startswith("wiki_source_recipe"):
            return data
    return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


def _coerce_int(value: Any) -> int:
    """A hand-authored cadence_days may be non-numeric ("weekly"); coerce to 0
    so parsing never crashes. validate_recipe then flags the non-positive value."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parse_recipe(mapping: dict[str, Any]) -> SourceRecipe:
    """Parse a recipe mapping into the typed contract (lenient; validation is
    a separate pass so the cockpit can still SHOW a malformed recipe)."""
    structural_errors: set[str] = set()
    pipelines_raw = mapping.get("pipelines")
    if pipelines_raw is None:
        pipelines_raw = []
    elif not isinstance(pipelines_raw, list):
        structural_errors.add("source_recipe_pipelines_invalid")
        pipelines_raw = []
    elif any(not isinstance(item, dict) for item in pipelines_raw):
        structural_errors.add("source_recipe_pipelines_invalid")
    pipelines = tuple(
        Pipeline(kind=str(p.get("kind") or ""), cadence_days=_coerce_int(p.get("cadence_days")))
        for p in pipelines_raw
        if isinstance(p, dict)
    )
    streams_raw = mapping.get("streams")
    if streams_raw is None:
        streams_raw = []
    elif not isinstance(streams_raw, list):
        structural_errors.add("source_recipe_streams_invalid")
        streams_raw = []
    elif any(not isinstance(item, dict) for item in streams_raw):
        structural_errors.add("source_recipe_streams_invalid")
    streams_out: list[Stream] = []
    for stream_raw in streams_raw:
        if not isinstance(stream_raw, dict):
            continue
        filters_raw = stream_raw.get("filters")
        if filters_raw is None:
            filters: dict[str, Any] = {}
        elif isinstance(filters_raw, dict):
            filters = dict(filters_raw)
        else:
            structural_errors.add("source_recipe_stream_filters_invalid")
            filters = {}
        targets_raw = stream_raw.get("target_pages")
        if targets_raw is None:
            targets_raw = []
        elif not isinstance(targets_raw, list):
            structural_errors.add("source_recipe_stream_target_pages_invalid")
            targets_raw = []
        streams_out.append(
            Stream(
                id=str(stream_raw.get("id") or ""),
                label=str(stream_raw.get("label") or stream_raw.get("id") or ""),
                selected=_as_bool(stream_raw.get("selected"), default=True),
                filters=filters,
                privacy=str(stream_raw.get("privacy") or "private_self"),
                target_pages=tuple(str(target) for target in targets_raw),
                skip_reason=str(stream_raw.get("skip_reason") or ""),
                cadence_days=_coerce_int(stream_raw.get("cadence_days")),
            )
        )
    streams = tuple(streams_out)
    ingest_raw = mapping.get("ingest")
    if ingest_raw is None:
        ingest: dict[str, Any] = {}
    elif isinstance(ingest_raw, dict):
        ingest = ingest_raw
    else:
        structural_errors.add("source_recipe_ingest_invalid")
        ingest = {}
    ingest_argv_raw = ingest.get("argv")
    if ingest_argv_raw is None:
        ingest_argv_raw = []
    elif not isinstance(ingest_argv_raw, list):
        structural_errors.add("source_recipe_ingest_argv_invalid")
        ingest_argv_raw = []
    auth_raw = mapping.get("auth")
    if auth_raw is not None and not isinstance(auth_raw, dict):
        structural_errors.add("source_recipe_auth_invalid")
    auth_scopes_raw = auth_raw.get("scopes") if isinstance(auth_raw, dict) else None
    if auth_scopes_raw is None:
        auth_scopes_raw = []
    elif not isinstance(auth_scopes_raw, list):
        structural_errors.add("source_recipe_auth_scopes_invalid")
        auth_scopes_raw = []
    auth = (
        AuthPointer(
            method=str(auth_raw.get("method") or "none"),
            ref=str(auth_raw.get("ref") or ""),
            scopes=tuple(str(x) for x in auth_scopes_raw),
            note=str(auth_raw.get("note") or ""),
        )
        if isinstance(auth_raw, dict)
        else None
    )
    schedule_raw = mapping.get("schedule")
    if schedule_raw is not None and not isinstance(schedule_raw, dict):
        structural_errors.add("source_recipe_schedule_invalid")
    schedule = (
        SyncSchedule(
            mode=str(schedule_raw.get("mode") or "on_demand"),
            cadence_days=_coerce_int(schedule_raw.get("cadence_days")),
            cron_hint=str(schedule_raw.get("cron_hint") or ""),
        )
        if isinstance(schedule_raw, dict)
        else None
    )
    return SourceRecipe(
        schema_version=str(mapping.get("schema_version") or SOURCE_RECIPE_SCHEMA_VERSION),
        platform=str(mapping.get("platform") or ""),
        locator=str(mapping.get("locator") or ""),
        source_kind=str(mapping.get("source_kind") or ""),
        pipelines=pipelines,
        streams=streams,
        how_to_export=str(mapping.get("how_to_export") or ""),
        ingest_argv=tuple(str(a) for a in ingest_argv_raw),
        mcp_hint=str(ingest.get("mcp_hint") or "") if ingest.get("mcp_hint") else "",
        auth=auth,
        schedule=schedule,
        structural_error_codes=tuple(sorted(structural_errors)),
        raw=dict(mapping),
    )


def validate_recipe(recipe: SourceRecipe) -> list[str]:
    """Structural + safety checks. CRITICAL: reject any credential-looking key —
    recipes are structural metadata, never secrets."""
    # Scan the unprojected source mapping before producing any field-specific
    # diagnostic. A token pasted into ``platform`` (for example) must never be
    # echoed by the otherwise-useful "unknown platform `<value>`" message.
    # Secret-bearing recipes therefore have exactly one stable, code-only
    # diagnostic; callers can fail closed without retaining any recipe value.
    if _recipe_contains_secret(recipe.raw):
        return [SOURCE_RECIPE_SAFETY_ERROR_CODE]

    errors: list[str] = list(recipe.structural_error_codes)
    if recipe.platform and recipe.platform not in PLATFORMS:
        errors.append(f"unknown platform `{recipe.platform}` (use {sorted(PLATFORMS)})")
    if not recipe.locator:
        errors.append("recipe.locator is required (platform-native id)")
    errors.extend(validate_source_kind(recipe.source_kind))
    if not recipe.pipelines:
        errors.append("recipe.pipelines is empty (declare at least one typed pipeline)")
    for pipeline in recipe.pipelines:
        if pipeline.kind not in PIPELINE_KINDS:
            errors.append(f"unknown pipeline kind `{pipeline.kind}` (use {sorted(PIPELINE_KINDS)})")
        if pipeline.cadence_days <= 0:
            errors.append(f"pipeline `{pipeline.kind}` needs a positive cadence_days")
    seen_ids: set[str] = set()
    for stream in recipe.streams:
        if not stream.id:
            errors.append("a stream has no id")
        elif stream.id in seen_ids:
            errors.append(f"duplicate stream id `{stream.id}`")
        seen_ids.add(stream.id)
        if stream.privacy and stream.privacy not in PRIVACY_LEVELS:
            errors.append(f"stream `{stream.id}`: unknown privacy `{stream.privacy}`")
        if not stream.selected and not stream.skip_reason:
            errors.append(f"stream `{stream.id}` is unselected without a skip_reason")
        if stream.cadence_days < 0:
            errors.append(f"stream `{stream.id}`: cadence_days must be non-negative")
    # Auth is a POINTER, never a secret. Validate the pointer shape only.
    if recipe.auth is not None:
        if recipe.auth.method not in AUTH_METHODS:
            errors.append(f"unknown auth.method `{recipe.auth.method}` (use {sorted(AUTH_METHODS)})")
        if recipe.auth.method != "none" and not recipe.auth.ref:
            errors.append(f"auth.ref is required when method is `{recipe.auth.method}`")
        # Soft guards that a ref is a POINTER, not an inlined secret.
        if recipe.auth.method == "env" and recipe.auth.ref and not _ENV_REF_RE.fullmatch(recipe.auth.ref):
            errors.append(f"auth.ref `{recipe.auth.ref}` does not look like an env var name (UPPER_SNAKE)")
        if recipe.auth.method in {"mcp", "keychain"} and _URLish_RE.search(recipe.auth.ref):
            errors.append("auth.ref looks like a URL/blob — it should be a short pointer id")
    if recipe.schedule is not None:
        errors.extend(validate_schedule(recipe.schedule.mode, recipe.schedule.cadence_days))
    else:
        errors.append("recipe.schedule is required (declare one_shot, on_demand, recurring, or event_driven)")
    # Secret smell: a recipe must never carry tokens/passwords/keys — neither as
    # a KEY name nor as a VALUE. Structural metadata only.
    for key in _flatten_keys(recipe.raw):
        if _SECRET_KEYS.search(key):
            errors.append(f"recipe must not contain credentials (found key `{key}`)")
    for value in _flatten_values(recipe.raw):
        if _SECRET_VALUE.search(value):
            errors.append("recipe must not contain a credential-looking value (redacted)")
            break  # one report is enough; never echo the secret
    return errors


# Key names that smell of secrets.
_SECRET_KEYS = re.compile(r"(token|secret|password|passwd|api[_-]?key|bearer|credential)", re.I)
# ``auth`` is a valid top-level pointer contract, but an ``auth`` value hidden
# inside free-form stream filters is executable credential material, not a
# selector. Treat the whole nested slot as secret even when its value has no
# provider-specific token shape.
_FILTER_SECRET_PATH = re.compile(r"(?:^|\.)filters\.auth(?:\.|$)", re.I)
# Shape guards for auth pointers (a ref must be a POINTER, not an inlined secret).
_ENV_REF_RE = re.compile(r"[A-Z][A-Z0-9_]*")
_URLish_RE = re.compile(r"(https?://|[A-Za-z0-9+/]{40,})")
# High-signal secret VALUE shapes: provider tokens + auth headers + long blobs.
_SECRET_VALUE = re.compile(
    r"(xox[baprs]-[A-Za-z0-9-]{8,}"  # Slack
    r"|gh[pousr]_[A-Za-z0-9]{20,}"  # GitHub
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|AIza[0-9A-Za-z_\-]{30,}"  # Google API key
    r"|sk-[A-Za-z0-9]{20,}"  # OpenAI-style
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"  # JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"  # PEM
    r"|(?:bearer|authorization)\s*[:=]\s*\S{8,})",  # inline auth header
    re.I,
)


def _recipe_contains_secret(value: Any) -> bool:
    """Return only a boolean so secret scans cannot accidentally echo input."""

    # The repository-wide detector is the canonical credential taxonomy. Scan
    # one deterministic serialization of the complete, unprojected mapping so
    # provider additions (GitHub, Anthropic, Stripe, connection URIs, etc.)
    # automatically protect recipes too. Any unserializable/non-finite value is
    # refused here rather than allowed into a downstream payload by accident.
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return True
    if any(finding.category == "secret" for finding in scan_text(serialized)):
        return True

    # Recipe-specific structural guards remain stricter than generic secret
    # detection: a credential-shaped key or a nested filters.auth slot is never
    # valid structural metadata, even when its placeholder value has low entropy.
    return any(
        _SECRET_KEYS.search(key) or _FILTER_SECRET_PATH.search(key)
        for key in _flatten_keys(value)
    ) or any(_SECRET_VALUE.search(item) for item in _flatten_values(value))


def _flatten_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            keys.append(path)
            keys.extend(_flatten_keys(v, path))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_flatten_keys(item, prefix))
    return keys


def _flatten_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for v in value.values():
            values.extend(_flatten_values(v))
    elif isinstance(value, list):
        for item in value:
            values.extend(_flatten_values(item))
    elif isinstance(value, str):
        values.append(value)
    return values
