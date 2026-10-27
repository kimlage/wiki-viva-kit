from __future__ import annotations

import json
from pathlib import Path

from wiki_core.ids import sha256_text


def cache_key(
    chunk_hash: str,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    *,
    context_sha256: str | None = None,
) -> str:
    """Keep legacy keys readable; new interpretation requests bind their context.

    Byte extraction stays independent. The optional digest describes the actual
    semantic envelope, never a global wiki hash or capture timestamp.
    """
    parts = [chunk_hash, prompt_version, schema_version, model_profile]
    if context_sha256 is not None:
        return sha256_text(json.dumps(["context-bound-v1", *parts, context_sha256],
                                      separators=(",", ":")))
    return sha256_text("|".join(parts))



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
