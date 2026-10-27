"""Contextual LLM pass delegated to the agent running the repo.

Architecture: `wiki_core` (deterministic code) gathers and selects the relevant
excerpts and assembles a context PACKET (request). The agent running the repo
(Claude/Codex/Gemini) performs the deep read and writes the RESULT to the cache.
There is no embedded LLM client in Python; the intelligence lives in the agent,
via a skill.

The honesty gate lives in `source_pending()` + `validate_result()`: while there
is any chunk without a valid result and `required_context_pass` is on, the
auditor fails — no source is consolidated without the deep read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_core.llm.cache import cache_key
from wiki_core.ids import sha256_text

CONTEXT_PASS_SCHEMA_VERSION = "wiki_llm_context_pass.v4"

# cache_key is always a sha256 hex digest (wiki_core.llm.cache.cache_key) and is
# used as a FILENAME in the cache dir: anything else is rejected to block path
# traversal (e.g. "../../memorias/x") through --record-result payloads.
CACHE_KEY_RE = re.compile(r"[0-9a-f]{64}")

DEFAULT_QUADRANTS = [
    "interior_individual",
    "exterior_individual",
    "interior_collective",
    "exterior_collective",
]

RESULT_REQUIRED_KEYS = [
    "cache_key",
    "source_id",
    "chunk_id",
    "prompt_version",
    "schema_version",
    "model_profile",
    "produced_by",
    "quadrants",
    "claims",
    "decisions",
    "actions",
    "risks",
    "uncertainties",
    "relationships",
    "sensitivity",
]

PERSPECTIVE_STATUSES = {
    "extracted",
    "not_applicable",
    "pending",
    "blocked",
    "skipped_with_reason",
}

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str, version: str) -> str:
    path = PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        path = PROMPTS_DIR / f"{name}.v1.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {name}.{version}")
    return path.read_text(encoding="utf-8")


def result_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def read_result(cache_dir: Path, key: str) -> dict[str, object] | None:
    if not CACHE_KEY_RE.fullmatch(key):
        return None
    path = result_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def validate_result(result: dict[str, object]) -> list[str]:
    if not isinstance(result, dict):
        return ["result_not_object"]
    errors: list[str] = []
    for key in RESULT_REQUIRED_KEYS:
        if key not in result:
            errors.append(f"missing_key:{key}")
    for key in ("cache_key", "source_id", "chunk_id", "prompt_version", "schema_version", "model_profile", "produced_by"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            errors.append(f"identity_invalid:{key}")
    quadrants = result.get("quadrants")
    if isinstance(quadrants, dict):
        for quadrant in DEFAULT_QUADRANTS:
            value = quadrants.get(quadrant)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"quadrant_empty:{quadrant}")
    else:
        errors.append("quadrants_not_object")
    sensitivity = result.get("sensitivity")
    if not isinstance(sensitivity, dict) or not isinstance(sensitivity.get("has_pii"), bool):
        errors.append("sensitivity_missing_has_pii")
    for field in ("claims", "decisions", "actions", "risks", "uncertainties", "relationships", "entities"):
        if field in result and not isinstance(result[field], list):
            errors.append(f"collection_not_list:{field}")
    schema_version = str(result.get("schema_version") or "")
    required_perspectives = result.get("perspectives_required") or []
    if not isinstance(required_perspectives, list) or any(not isinstance(x, str) for x in required_perspectives):
        errors.append("perspectives_required_not_list")
        required_perspectives = []
    if schema_version.endswith(".v3") or schema_version.endswith(".v4") or required_perspectives:
        perspectives = result.get("perspectives")
        if not isinstance(perspectives, dict):
            errors.append("perspectives_not_object")
        else:
            for perspective_id in required_perspectives if isinstance(required_perspectives, list) else []:
                block = perspectives.get(str(perspective_id))
                if not isinstance(block, dict):
                    errors.append(f"perspective_missing:{perspective_id}")
                    continue
                status = str(block.get("status") or "")
                if status not in PERSPECTIVE_STATUSES:
                    errors.append(f"perspective_invalid_status:{perspective_id}")
                if status in {"not_applicable", "blocked", "skipped_with_reason"}:
                    if not str(block.get("reason") or "").strip():
                        errors.append(f"perspective_missing_reason:{perspective_id}")
    return errors


def write_result(cache_dir: Path, result: dict[str, object]) -> Path:
    errors = validate_result(result)
    if errors:
        raise ValueError("invalid LLM pass result: " + ", ".join(errors))
    key = str(result["cache_key"])
    if not CACHE_KEY_RE.fullmatch(key):
        raise ValueError(
            f"invalid cache_key {key!r}: expected a sha256 hex digest "
            "(64 lowercase hex chars); refusing to use it as a cache filename"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = result_path(cache_dir, key)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _source_hash(manifest: dict[str, object]) -> str:
    return str(manifest.get("hash_sha256") or manifest.get("source_id"))



# Only semantic inputs delivered to the reader belong in interpretation identity.
# Capture timestamps, source-wide hashes and aggregate counters do not.
_CONTEXT_FIELDS = (
    "prompt_name", "prompt", "source_context", "quadrants_required",
    "quadrant_map", "quadrant_semantics", "quadrant_boundary_rule", "root_entity",
    "input_channel", "input_stage_status", "target_pages", "perspectives_required",
    "perspectives_optional", "block_context_package",
)


def context_fingerprint(request: dict, provenance: dict) -> str:
    envelope = {key: request.get(key) for key in _CONTEXT_FIELDS}
    envelope["provenance"] = provenance
    return sha256_text(json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False))


def result_matches_request(result: object, request: dict, row: dict, *, recording=False) -> bool:
    """Validate the recorded interpretation, rather than file existence.

    Legacy requests remain inspectable with their original identities. They
    cannot satisfy a new contextual request. For a bound result, a stable origin
    plus unchanged semantic inputs/chunk permits reuse across source versions;
    its original source/chunk IDs remain visible as the provenance of that read.
    New recordings must name the exact emitted source and chunk.
    """
    if not isinstance(result, dict) or not isinstance(row, dict):
        return False
    key = row.get("cache_key")
    if not isinstance(key, str) or not CACHE_KEY_RE.fullmatch(key) or result.get("cache_key") != key:
        return False
    validation = dict(result)
    validation["perspectives_required"] = request.get("perspectives_required", result.get("perspectives_required", []))
    if validate_result(validation):
        return False
    for perspective in request.get("perspectives_required", []):
        if result.get("perspectives", {}).get(perspective, {}).get("status") in {"pending", "blocked"}:
            return False
    for field in ("prompt_version", "schema_version", "model_profile"):
        if request.get(field) is not None and result.get(field) != request[field]:
            return False
    bound = row.get("context_sha256")
    if (request.get("context_binding_version") == 1 or result.get("context_sha256") is not None) and bound is None:
        return False
    if bound is not None:
        if (not isinstance(row.get("text"), str)
                or sha256_text(row["text"]) != row.get("chunk_hash_sha256")):
            return False
        if (not isinstance(bound, str) or not CACHE_KEY_RE.fullmatch(bound)
                or result.get("context_sha256") != bound
                or result.get("chunk_hash_sha256") != row.get("chunk_hash_sha256")
                or context_fingerprint(request, row.get("provenance", {})) != bound
                or cache_key(str(row.get("chunk_hash_sha256")), str(request.get("prompt_version")),
                             str(request.get("schema_version")), str(request.get("model_profile")),
                             context_sha256=bound) != key):
            return False
    if recording or bound is None:
        expected_source = row.get("source_id", request.get("source_id"))
        if expected_source is not None and result.get("source_id") != expected_source:
            return False
        if row.get("chunk_id") is not None and result.get("chunk_id") != row["chunk_id"]:
            return False
    return True


def read_matching_result(cache_dir: Path, request: dict, row: dict) -> dict | None:
    key = row.get("cache_key") if isinstance(row, dict) else None
    result = read_result(cache_dir, key) if isinstance(key, str) else None
    return result if result_matches_request(result, request, row) else None


def build_context_request(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    *,
    prompt_name: str = "context_deep_read",
    quadrants: list[str] | None = None,
    perspectives_required: list[str] | None = None,
    perspectives_optional: list[str] | None = None,
    root_entity: dict[str, object] | None = None,
    input_channel: dict[str, object] | None = None,
    quadrant_map: dict[str, object] | None = None,
    quadrant_semantics: dict[str, object] | None = None,
    quadrant_boundary_rule: str | None = None,
    target_pages: list[str] | None = None,
    input_stage_status: str | None = None,
    block_context_package: dict[str, object] | None = None,
) -> dict[str, object]:
    """Assemble the packet that the repo agent executes. Includes the chunk text,
    the versioned prompt, the output schema and the per-chunk cache status.

    ``block_context_package`` (v2, read-only) carries the resolved block stack of
    the ingestion center — the combined lenses (quadrants + any perspective
    bundle), each with its local label, canonical operational test and referenced
    perspective page, plus the write policy and target obligations. The agent is
    asked to honor it; nothing is written outside the PR gate."""
    quadrants = quadrants or DEFAULT_QUADRANTS
    perspectives_required = perspectives_required or []
    perspectives_optional = perspectives_optional or []
    target_pages = target_pages or []
    source_hash = _source_hash(manifest)  # packet metadata (not part of the cache_key)
    prompt_text = load_prompt(prompt_name, prompt_version)
    result_required_keys = [*RESULT_REQUIRED_KEYS, "context_sha256", "chunk_hash_sha256"]
    if perspectives_required:
        result_required_keys.append("perspectives")
    request = {
        "kind": "llm_context_request",
        "context_binding_version": 1,
        "source_context": manifest.get("context", ""),
        "schema_version": schema_version,
        "context_pass_schema_version": CONTEXT_PASS_SCHEMA_VERSION,
        "source_id": manifest.get("source_id"),
        "source_hash_sha256": source_hash,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "model_profile": model_profile,
        "quadrants_required": quadrants,
        "quadrant_map": quadrant_map or {},
        "quadrant_semantics": quadrant_semantics or {},
        "quadrant_boundary_rule": quadrant_boundary_rule or "",
        "root_entity": root_entity or {},
        "input_channel": input_channel or {},
        "input_stage_status": input_stage_status or "",
        "target_pages": target_pages,
        "perspectives_required": perspectives_required,
        "perspectives_optional": perspectives_optional,
        "block_context_package": block_context_package or {},
        "result_required_keys": result_required_keys,
        "prompt": prompt_text,
        "chunks": [],
        "pending_llm_calls": 0,
        "cached_calls": 0,
        "instructions": (
            "The agent running the repo performs the deep read of each chunk with "
            "result_exists=false, produces an object matching result_required_keys "
            "(cache_key = the chunk's) and writes it via "
            "`scripts/wiki_llm_context_pass.py --record-result`. Never write "
            "canonical memory directly."
        ),
    }

    for chunk in chunks:
        source_id = chunk.get("source_id", manifest.get("source_id"))
        origin = chunk.get("source_origin") or manifest.get("source_origin") or {}
        origin_id = origin.get("id") if isinstance(origin, dict) else None
        # Missing origin is not guessed from a basename, URL or account.
        provenance = {"origin_id": origin_id} if origin_id else {"source_id": source_id}
        for field in ("account_id", "provider_account_id"):
            if chunk.get(field, manifest.get(field)) is not None:
                provenance[field] = chunk.get(field, manifest.get(field))
        if chunk.get("context") is not None:
            provenance["context"] = chunk["context"]
        bound = context_fingerprint(request, provenance)
        chunk_hash = str(chunk["hash_sha256"])
        if not isinstance(chunk.get("text"), str) or sha256_text(chunk["text"]) != chunk_hash:
            raise ValueError("context_chunk_hash_mismatch: text must match its digest")
        row = {
            "chunk_id": chunk["chunk_id"], "source_id": source_id,
            "chunk_hash_sha256": chunk_hash, "context_sha256": bound,
            "provenance": provenance,
            "cache_key": cache_key(chunk_hash, prompt_version, schema_version,
                                   model_profile, context_sha256=bound),
            "token_estimate": chunk.get("token_estimate"), "text": chunk.get("text", ""),
        }
        existing = read_matching_result(cache_dir, request, row)
        row["result_exists"] = existing is not None
        if existing is not None:
            row["result_source_id"] = existing.get("source_id")
            row["result_chunk_id"] = existing.get("chunk_id")
        request["chunks"].append(row)
        request["cached_calls" if existing is not None else "pending_llm_calls"] += 1
    request["instructions"] += " Copy context_sha256 and chunk_hash_sha256 from the chunk; retain its exact source_id and chunk_id."
    return request


def source_pending(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    **context_inputs,
) -> int:
    """Use the exact same request identity and validation as packet generation."""
    return int(build_context_request(manifest, chunks, cache_dir, prompt_version,
                                    schema_version, model_profile, **context_inputs)["pending_llm_calls"])
