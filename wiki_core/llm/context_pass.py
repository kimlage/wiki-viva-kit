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
from pathlib import Path

from wiki_core.llm.cache import cache_key

CONTEXT_PASS_SCHEMA_VERSION = "wiki_llm_context_pass.v2"

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
    path = result_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def validate_result(result: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for key in RESULT_REQUIRED_KEYS:
        if key not in result:
            errors.append(f"missing_key:{key}")
    quadrants = result.get("quadrants")
    if isinstance(quadrants, dict):
        for quadrant in DEFAULT_QUADRANTS:
            value = str(quadrants.get(quadrant) or "").strip()
            if not value:
                errors.append(f"quadrant_empty:{quadrant}")
    else:
        errors.append("quadrants_not_object")
    sensitivity = result.get("sensitivity")
    if not isinstance(sensitivity, dict) or "has_pii" not in sensitivity:
        errors.append("sensitivity_missing_has_pii")
    return errors


def write_result(cache_dir: Path, result: dict[str, object]) -> Path:
    errors = validate_result(result)
    if errors:
        raise ValueError("invalid LLM pass result: " + ", ".join(errors))
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = str(result["cache_key"])
    path = result_path(cache_dir, key)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _source_hash(manifest: dict[str, object]) -> str:
    return str(manifest.get("hash_sha256") or manifest.get("source_id"))


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
) -> dict[str, object]:
    """Assemble the packet that the repo agent executes. Includes the chunk text,
    the versioned prompt, the output schema and the per-chunk cache status."""
    quadrants = quadrants or DEFAULT_QUADRANTS
    source_hash = _source_hash(manifest)  # packet metadata (not part of the cache_key)
    prompt_text = load_prompt(prompt_name, prompt_version)
    rows: list[dict[str, object]] = []
    pending = 0
    cached = 0
    for chunk in chunks:
        chunk_hash = str(chunk["hash_sha256"])
        key = cache_key(chunk_hash, prompt_version, schema_version, model_profile)
        existing = read_result(cache_dir, key)
        if existing is None:
            pending += 1
        else:
            cached += 1
        rows.append(
            {
                "chunk_id": chunk["chunk_id"],
                "chunk_hash_sha256": chunk_hash,
                "cache_key": key,
                "token_estimate": chunk.get("token_estimate"),
                "text": chunk.get("text", ""),
                "result_exists": existing is not None,
            }
        )
    return {
        "kind": "llm_context_request",
        "schema_version": schema_version,
        "context_pass_schema_version": CONTEXT_PASS_SCHEMA_VERSION,
        "source_id": manifest.get("source_id"),
        "source_hash_sha256": source_hash,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "model_profile": model_profile,
        "quadrants_required": quadrants,
        "result_required_keys": RESULT_REQUIRED_KEYS,
        "prompt": prompt_text,
        "chunks": rows,
        "pending_llm_calls": pending,
        "cached_calls": cached,
        "instructions": (
            "The agent running the repo performs the deep read of each chunk with "
            "result_exists=false, produces an object matching result_required_keys "
            "(cache_key = the chunk's) and writes it via "
            "`scripts/wiki_llm_context_pass.py --record-result`. Never write "
            "canonical memory directly."
        ),
    }


def source_pending(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
) -> int:
    """Number of chunks with no recorded LLM pass result (for the gate)."""
    pending = 0
    for chunk in chunks:
        key = cache_key(str(chunk["hash_sha256"]), prompt_version, schema_version, model_profile)
        if read_result(cache_dir, key) is None:
            pending += 1
    return pending
