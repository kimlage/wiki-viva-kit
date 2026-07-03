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

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

SOURCE_RECIPE_SCHEMA_VERSION = "wiki_source_recipe.v1"

# Typed pipeline kinds (independently cadenced) — OpenMetadata pipelineType
# analogue, scoped to what this wiki actually runs.
PIPELINE_KINDS = frozenset({"metadata", "content", "deep_read", "usage"})
PLATFORMS = frozenset(
    {"slack", "gchat", "whatsapp", "gmail", "drive", "web", "repo", "file", "calendar", "manual"}
)
PRIVACY_LEVELS = frozenset(
    {"private_self", "private_sensitive_allowed", "team_shared", "public_ok"}
)
# How the operator's credential is REACHED (a pointer, never the secret itself).
AUTH_METHODS = frozenset({"env", "keychain", "onepassword", "oauth_file", "mcp", "none"})
# How often the source is meant to be synced.
SCHEDULE_MODES = frozenset({"on_demand", "recurring", "event_driven"})

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
    pipelines: tuple[Pipeline, ...]
    streams: tuple[Stream, ...]
    how_to_export: str
    ingest_argv: tuple[str, ...]
    mcp_hint: str
    auth: AuthPointer | None = None
    schedule: SyncSchedule | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "locator": self.locator,
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
    pipelines = tuple(
        Pipeline(kind=str(p.get("kind") or ""), cadence_days=_coerce_int(p.get("cadence_days")))
        for p in (mapping.get("pipelines") or [])
        if isinstance(p, dict)
    )
    streams = tuple(
        Stream(
            id=str(s.get("id") or ""),
            label=str(s.get("label") or s.get("id") or ""),
            selected=_as_bool(s.get("selected"), default=True),
            filters=dict(s.get("filters") or {}),
            privacy=str(s.get("privacy") or "private_self"),
            target_pages=tuple(str(t) for t in (s.get("target_pages") or [])),
            skip_reason=str(s.get("skip_reason") or ""),
            cadence_days=_coerce_int(s.get("cadence_days")),
        )
        for s in (mapping.get("streams") or [])
        if isinstance(s, dict)
    )
    ingest = mapping.get("ingest") or {}
    auth_raw = mapping.get("auth")
    auth = (
        AuthPointer(
            method=str(auth_raw.get("method") or "none"),
            ref=str(auth_raw.get("ref") or ""),
            scopes=tuple(str(x) for x in (auth_raw.get("scopes") or [])),
            note=str(auth_raw.get("note") or ""),
        )
        if isinstance(auth_raw, dict)
        else None
    )
    schedule_raw = mapping.get("schedule")
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
        pipelines=pipelines,
        streams=streams,
        how_to_export=str(mapping.get("how_to_export") or ""),
        ingest_argv=tuple(str(a) for a in (ingest.get("argv") or [])),
        mcp_hint=str(ingest.get("mcp_hint") or "") if ingest.get("mcp_hint") else "",
        auth=auth,
        schedule=schedule,
        raw=dict(mapping),
    )


def validate_recipe(recipe: SourceRecipe) -> list[str]:
    """Structural + safety checks. CRITICAL: reject any credential-looking key —
    recipes are structural metadata, never secrets."""
    errors: list[str] = []
    if recipe.platform and recipe.platform not in PLATFORMS:
        errors.append(f"unknown platform `{recipe.platform}` (use {sorted(PLATFORMS)})")
    if not recipe.locator:
        errors.append("recipe.locator is required (platform-native id)")
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
        if recipe.schedule.mode not in SCHEDULE_MODES:
            errors.append(f"unknown schedule.mode `{recipe.schedule.mode}` (use {sorted(SCHEDULE_MODES)})")
        if recipe.schedule.mode == "recurring" and recipe.schedule.cadence_days <= 0:
            errors.append("a recurring schedule needs a positive cadence_days")
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


def _flatten_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            keys.append(str(k))
            keys.extend(_flatten_keys(v, str(k)))
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
