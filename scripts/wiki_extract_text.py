#!/usr/bin/env python3
"""Extract source text and stable chunks before any LLM pass."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.chunking import chunk_text
from wiki_core.config import load_config
from wiki_core.detectors import scan_file, scan_text
from wiki_core.extractors import extract_source
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-derived", action="store_true")
    args = parser.parse_args()

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    paths.ensure()
    manifest = build_manifest(args.source, args.context)
    source_id = str(manifest["source_id"])
    extracted = extract_source(args.source, str(manifest["source_type"]))
    target_tokens = int(config.llm.get("chunk_target_tokens", 1200))
    overlap_tokens = int(config.llm.get("chunk_overlap_tokens", 150))
    chunks = chunk_text(source_id, extracted.text, target_tokens, overlap_tokens)
    payload = {
        "schema_version": "wiki_extracted_text.v1",
        "source_id": source_id,
        "source_uri": args.source,
        "source_type": manifest["source_type"],
        "context": args.context,
        "warnings": extracted.warnings,
        "text_characters": len(extracted.text),
        "units": extracted.units,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "hash_sha256": chunk.hash_sha256,
                "token_estimate": chunk.token_estimate,
                "text": chunk.text,
            }
            for chunk in chunks
        ],
    }
    preview = {key: value for key, value in payload.items() if key not in {"units", "chunks"}}
    preview["unit_count"] = len(extracted.units)
    preview["chunk_count"] = len(chunks)
    if args.dry_run and not args.write_derived:
        print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    # Scan-first: blocks BEFORE persisting if the source (raw or extracted text)
    # has a secret. Same guarantee as the wiki_ingest.py orchestrator.
    src_path = Path(args.source).expanduser()
    findings = list(scan_file(src_path)) if src_path.is_file() else []
    if extracted.text:
        findings += list(scan_text(extracted.text))
    secrets = [f for f in findings if f.category == "secret"]
    if secrets:
        print(
            f"BLOCKED: {len(secrets)} secret(s) in the source; nothing was written to "
            "data/derived. Remove the secret before extracting.",
            file=sys.stderr,
        )
        return 2
    write_manifest(manifest, paths.source_manifests)
    text_path = paths.source_text / f"{source_id}.json"
    chunk_path = paths.chunks / f"{source_id}.json"
    text_payload = {key: value for key, value in payload.items() if key != "chunks"}
    text_path.write_text(json.dumps(text_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    chunk_path.write_text(
        json.dumps(
            {
                "schema_version": "wiki_chunks.v1",
                "source_id": source_id,
                "source_hash_sha256": manifest.get("hash_sha256"),
                "chunks": payload["chunks"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(text_path.relative_to(ROOT))
    print(chunk_path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
