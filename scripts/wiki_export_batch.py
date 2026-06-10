#!/usr/bin/env python3
"""Exports the pending LLM context packets in the Batches API format.

A COST lever (-50%) that RESPECTS the architecture: this script does NOT call
any model. It only TRANSFORMS, deterministically, the
`*-llm-context-request.json` files already emitted by the pipeline into a JSONL of
Anthropic Message Batches API requests. Whoever runs the repo (agent/human) submits
the JSONL, then writes the results back with
`scripts/wiki_llm_context_pass.py --record-result` (provenance flows through
custom_id = chunk cache_key).

The intelligence stays outside Python: here there is only JSON reading + assembly of
the batch envelope. No network, no LLM client, no secret.

Examples:
  python3 scripts/wiki_export_batch.py > batch.jsonl
  python3 scripts/wiki_export_batch.py --model claude-haiku-4-5 --max-tokens 1500
  python3 scripts/wiki_export_batch.py --include-cached   # reprocess everything
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.paths import WikiPaths

# Conservative default (most capable model). The cost analysis recommends Sonnet/
# Haiku + Batches for the chunks; switch with --model when the source is simple.
_DEFAULT_MODEL = "claude-opus-4-8"


def build_batch_requests(
    request_files: list[Path],
    *,
    model: str,
    max_tokens: int,
    include_cached: bool,
) -> list[dict[str, object]]:
    """Reads the emitted requests and returns the batch lines (one per chunk)."""
    requests: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in sorted(request_files):
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # A corrupt request must be VISIBLE (its chunks silently dropping
            # out of the batch hides a pipeline bug), but must not abort the rest.
            print(f"WARNING: invalid request JSON skipped: {path.name} ({exc})", file=sys.stderr)
            continue
        prompt = str(packet.get("prompt", ""))
        for chunk in packet.get("chunks", []):
            if not include_cached and chunk.get("result_exists"):
                continue
            cache_key = str(chunk.get("cache_key", ""))
            if not cache_key or cache_key in seen:
                continue
            seen.add(cache_key)
            content = f"{prompt}\n\n--- CHUNK ({chunk.get('chunk_id')}) ---\n{chunk.get('text', '')}"
            requests.append(
                {
                    "custom_id": cache_key,
                    "params": {
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": content}],
                    },
                }
            )
    return requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=_DEFAULT_MODEL, help=f"model (default {_DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=2000, help="max_tokens per request (default 2000)")
    parser.add_argument(
        "--include-cached",
        action="store_true",
        help="include chunks that already have a result (reprocessing)",
    )
    parser.add_argument("--out", type=Path, help="output file (default stdout)")
    args = parser.parse_args(argv)

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    request_files = list(paths.extraction_events.glob("*-llm-context-request.json"))

    requests = build_batch_requests(
        request_files,
        model=args.model,
        max_tokens=args.max_tokens,
        include_cached=args.include_cached,
    )

    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests)
    payload = lines + ("\n" if lines else "")
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(
            f"{len(requests)} batch request(s) -> {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
