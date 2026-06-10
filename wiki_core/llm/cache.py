from __future__ import annotations

import json
from pathlib import Path

from wiki_core.ids import sha256_text


def cache_key(
    chunk_hash: str,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
) -> str:
    """Deterministic cache key for the per-chunk LLM pass.

    Does NOT include the hash of the WHOLE SOURCE (finding 4): the deep-read
    result is a function of the chunk's CONTENT + prompt + schema + model, not of
    the source. Including the source_hash invalidated 100% of the cache on every
    source edit, even for identical chunks; now chunks with the same text dedup
    the result across versions (and even across different sources).
    """
    return sha256_text("|".join([chunk_hash, prompt_version, schema_version, model_profile]))


def cache_summary(cache_dir: Path) -> dict[str, object]:
    files = sorted(cache_dir.glob("*.json"))
    prompt_versions: dict[str, int] = {}
    schema_versions: dict[str, int] = {}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        prompt = str(data.get("prompt_version", "unknown"))
        schema = str(data.get("schema_version", "unknown"))
        prompt_versions[prompt] = prompt_versions.get(prompt, 0) + 1
        schema_versions[schema] = schema_versions.get(schema, 0) + 1
    return {
        "cache_files": len(files),
        "prompt_versions": prompt_versions,
        "schema_versions": schema_versions,
    }
