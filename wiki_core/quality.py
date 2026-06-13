from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values as _list_values
from wiki_core.frontmatter import parse_frontmatter_flat as parse_frontmatter
from wiki_core.graph import build_page_graph
from wiki_core.graph.page_graph import DEFAULT_ORPHAN_EXEMPT_TYPES, PageGraph
from wiki_core.llm.cache import cache_key
from wiki_core.llm.context_pass import CONTEXT_PASS_SCHEMA_VERSION
from wiki_core.paths import WikiPaths

QUALITY_REPORT_SCHEMA_VERSION = "wiki_quality_report.v1"

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_]+")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

NAV_EXEMPT_TYPES = DEFAULT_ORPHAN_EXEMPT_TYPES | {"ingestion_event"}
EVENT_INDEX_FILENAMES = {"readme.md", "index.md"}
QUALITY_EXEMPT_ALL = "all"


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def strip_code_fences(text: str) -> str:
    return CODE_FENCE_RE.sub("", text)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def estimate_tokens(text: str) -> int:
    # Cheap deterministic approximation: prose tokens are usually close to
    # 1.3x words for mixed Markdown. This is telemetry, not a budget gate.
    return int(len(words(text)) * 1.3)


def useful_lines(body: str) -> list[str]:
    useful: list[str] = []
    for raw in strip_code_fences(body).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line in {"---", "| --- |"}:
            continue
        if line.startswith("<!--"):
            continue
        useful.append(line)
    return useful


def normalize_repeated_block(text: str) -> str:
    text = MARKDOWN_LINK_RE.sub(lambda m: m.group(0).split("](", 1)[0] + "]", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\s+", " ", text.strip().lower())
    return text


def repeated_blocks_for_page(body: str) -> set[str]:
    blocks: set[str] = set()
    for raw in re.split(r"\n\s*\n", strip_code_fences(body)):
        block = " ".join(line.strip() for line in raw.splitlines() if line.strip())
        if not block or block.startswith("#") or block.startswith("|"):
            continue
        normalized = normalize_repeated_block(block)
        if len(normalized) >= 120:
            blocks.add(normalized)
    return blocks


def _quality_exemptions(values: dict[str, Any]) -> set[str]:
    return set(_list_values(values.get("quality_exempt")))


def _is_quality_exempt(values: dict[str, Any], key: str) -> bool:
    exemptions = _quality_exemptions(values)
    return QUALITY_EXEMPT_ALL in exemptions or key in exemptions


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _chunk_payloads(paths: WikiPaths) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not paths.chunks.exists():
        return payloads
    for path in sorted(paths.chunks.rglob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            payloads.append({"path": path, "source_id": data.get("source_id"), "chunks": chunks})
    return payloads


def _event_pages(paths: WikiPaths) -> list[Path]:
    if not paths.ingest_events_dir.exists():
        return []
    return sorted(paths.ingest_events_dir.rglob("*.md"))


def _is_ingestion_event_page(path: Path, values: dict[str, Any]) -> bool:
    if path.name.lower() in EVENT_INDEX_FILENAMES:
        return False
    if values.get("page_type") == "ingestion_event":
        return True
    # Legacy migrations sometimes wrote normalized event files in the canonical
    # events directory while keeping a broader source/catalog page type. The
    # directory is authoritative for quality metrics once the page carries event
    # or source identity.
    return bool(values.get("event_id") or values.get("source_id"))


def _is_event_rel(paths: WikiPaths, rel: str) -> bool:
    if not paths.ingest_events_dir.exists():
        return False
    try:
        prefix = paths.ingest_events_dir.relative_to(paths.root).as_posix().rstrip("/") + "/"
    except ValueError:
        return False
    name = Path(rel).name.lower()
    return rel.startswith(prefix) and name not in EVENT_INDEX_FILENAMES


def operational_coverage(
    root: Path,
    graph: PageGraph,
    contexts: tuple[str, ...],
    *,
    default_context: str = "system",
) -> dict[str, Any]:
    """Deterministic coverage of the operational model (Fase 5).

    Pure over the page graph: it crosses the ``responsibilities`` / ``roles`` /
    ``actions`` frontmatter lists to surface four gaps. Telemetry only -- the
    gate (opt-in, loose thresholds) lives in ``scripts/wiki_quality_report.py``.
    """
    roles: dict[str, dict[str, Any]] = {}
    resps: dict[str, dict[str, Any]] = {}
    acts: dict[str, dict[str, Any]] = {}
    role_contexts: dict[str, set[str]] = defaultdict(set)
    for rel, node in graph.nodes.items():
        if node.page_type not in {"role", "responsibility", "action"}:
            continue
        values = parse_frontmatter(root / rel)
        page_id = str(values.get("page_id") or "").strip()
        if not page_id:
            continue
        record = {
            "rel": rel,
            "page_id": page_id,
            "context": node.context,
            "roles": tuple(_list_values(values.get("roles"))),
            "responsibilities": tuple(_list_values(values.get("responsibilities"))),
            "actions": tuple(_list_values(values.get("actions"))),
        }
        if node.page_type == "role":
            roles[page_id] = record
            role_contexts[node.context].add(page_id)
        elif node.page_type == "responsibility":
            resps[page_id] = record
        else:
            acts[page_id] = record

    # An action references a responsibility iff either side lists the other.
    resp_has_action: dict[str, bool] = {pid: bool(r["actions"]) for pid, r in resps.items()}
    action_has_resp: dict[str, bool] = {pid: bool(a["responsibilities"]) for pid, a in acts.items()}
    for aid, action in acts.items():
        for rid in action["responsibilities"]:
            if rid in resp_has_action:
                resp_has_action[rid] = True
        if any(aid in r["actions"] for r in resps.values()):
            action_has_resp[aid] = True

    responsibilities_without_action = sorted(
        resps[pid]["rel"] for pid, has in resp_has_action.items() if not has
    )
    orphan_actions = sorted(
        acts[pid]["rel"] for pid, has in action_has_resp.items() if not has
    )
    contexts_without_role = sorted(
        ctx for ctx in contexts if ctx != default_context and not role_contexts.get(ctx)
    )

    mismatches: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for rid, role in roles.items():
        for resp_id in role["responsibilities"]:
            resp = resps.get(resp_id)
            if resp is not None and rid not in resp["roles"]:
                key = (rid, resp_id)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    mismatches.append({"role": rid, "responsibility": resp_id})
    for resp_id, resp in resps.items():
        for rid in resp["roles"]:
            role = roles.get(rid)
            if role is not None and resp_id not in role["responsibilities"]:
                key = (rid, resp_id)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    mismatches.append({"role": rid, "responsibility": resp_id})
    mismatches.sort(key=lambda m: (m["role"], m["responsibility"]))

    return {
        "responsibilities_without_action": responsibilities_without_action,
        "contexts_without_role": contexts_without_role,
        "orphan_actions": orphan_actions,
        "role_responsibility_edge_mismatch": mismatches,
    }


def build_quality_report(root: Path, config: WikiConfig) -> dict[str, Any]:
    paths = WikiPaths(root, config)
    graph = build_page_graph(root, config)
    pages: list[dict[str, Any]] = []
    repeated_index: dict[str, list[str]] = defaultdict(list)
    body_text_by_rel: dict[str, str] = {}
    frontmatter_by_rel: dict[str, dict[str, Any]] = {}
    quality_exempt_pages: list[dict[str, str]] = []
    quality_exemption_missing_reason: list[str] = []

    for rel, node in graph.nodes.items():
        page_path = root / rel
        values = parse_frontmatter(page_path)
        frontmatter_by_rel[rel] = values
        text = page_path.read_text(encoding="utf-8", errors="replace")
        body = strip_frontmatter(text)
        body_text_by_rel[rel] = body
        body_words = len(words(body))
        useful = useful_lines(body)
        outbound = len(node.outbound_links)
        body_links = len(node.outbound_body_links)
        pages.append(
            {
                "path": rel,
                "page_type": node.page_type,
                "context": node.context,
                "words": body_words,
                "estimated_tokens": estimate_tokens(body),
                "useful_lines": len(useful),
                "outbound_links": outbound,
                "body_links": body_links,
                "link_density_per_1000_words": round(outbound / max(body_words, 1) * 1000, 2),
                "information_density_per_1000_words": round(len(useful) / max(body_words, 1) * 1000, 2),
                "quality_exempt": sorted(_quality_exemptions(values)),
            }
        )
        if _quality_exemptions(values):
            reason = str(values.get("quality_exempt_reason") or "").strip()
            quality_exempt_pages.append(
                {
                    "path": rel,
                    "exemptions": ", ".join(sorted(_quality_exemptions(values))),
                    "reason": reason,
                }
            )
            if not reason:
                quality_exemption_missing_reason.append(rel)
        if not _is_event_rel(paths, rel):
            for block in repeated_blocks_for_page(body):
                repeated_index[block].append(rel)

    by_type = Counter(page["page_type"] for page in pages)
    by_context = Counter(page["context"] for page in pages)
    low_density_pages = [
        page["path"]
        for page in pages
        if page["page_type"] not in NAV_EXEMPT_TYPES and page["useful_lines"] < 3
        and not _is_quality_exempt(frontmatter_by_rel.get(page["path"], {}), "low_density")
    ]
    thin_link_pages = [
        page["path"]
        for page in pages
        if page["page_type"] not in NAV_EXEMPT_TYPES and page["outbound_links"] < 1
    ]

    repeated_blocks: list[dict[str, Any]] = []
    bad_repetition: list[dict[str, Any]] = []
    for block, rels in sorted(repeated_index.items()):
        unique_rels = sorted(set(rels))
        repeated_rels = [
            rel
            for rel in unique_rels
            if not _is_quality_exempt(frontmatter_by_rel.get(rel, {}), "repetition")
            and not _is_quality_exempt(frontmatter_by_rel.get(rel, {}), "bad_repetition")
        ]
        if len(repeated_rels) < 2:
            continue
        unique_rels = repeated_rels
        if len(unique_rels) < 2:
            continue
        contexts = {graph.nodes[rel].context for rel in unique_rels if rel in graph.nodes}
        types = {graph.nodes[rel].page_type for rel in unique_rels if rel in graph.nodes}
        record = {
            "text_preview": block[:180],
            "pages": unique_rels,
            "contexts": sorted(contexts),
            "page_types": sorted(types),
        }
        repeated_blocks.append(record)
        grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
        for rel in unique_rels:
            node = graph.nodes.get(rel)
            if node:
                grouped[(node.context, node.page_type)].append(rel)
        for (context, page_type), group_rels in sorted(grouped.items()):
            if len(group_rels) > 1:
                bad_repetition.append(
                    {
                        **record,
                        "pages": sorted(group_rels),
                        "contexts": [context],
                        "page_types": [page_type],
                    }
                )

    chunk_payloads = _chunk_payloads(paths)
    prompt_version = str(
        dict(config.llm.get("prompt_versions", {})).get("context_deep_read", "v1")
    )
    schema_version = CONTEXT_PASS_SCHEMA_VERSION
    model_profile = str(config.llm.get("default_model_profile", "deep_context"))
    source_costs: list[dict[str, Any]] = []
    total_chunks = 0
    total_tokens = 0
    cached_calls = 0
    pending_calls = 0
    for payload in chunk_payloads:
        source_chunks = [c for c in payload["chunks"] if isinstance(c, dict)]
        source_tokens = 0
        source_cached = 0
        source_pending = 0
        for chunk in source_chunks:
            total_chunks += 1
            try:
                token_estimate = int(chunk.get("token_estimate") or 0)
            except (TypeError, ValueError):
                token_estimate = estimate_tokens(str(chunk.get("text") or ""))
            source_tokens += token_estimate
            chunk_hash = str(chunk.get("hash_sha256") or "")
            key = cache_key(chunk_hash, prompt_version, schema_version, model_profile) if chunk_hash else ""
            if key and (paths.llm_cache / f"{key}.json").exists():
                source_cached += 1
            else:
                source_pending += 1
        total_tokens += source_tokens
        cached_calls += source_cached
        pending_calls += source_pending
        source_costs.append(
            {
                "source_id": str(payload.get("source_id") or ""),
                "chunks": len(source_chunks),
                "estimated_tokens": source_tokens,
                "cached_calls": source_cached,
                "pending_calls": source_pending,
            }
        )

    events_total = 0
    events_without_consolidated_into: list[str] = []
    events_without_impact_closure: list[str] = []
    for path in _event_pages(paths):
        rel = path.relative_to(root).as_posix()
        values = parse_frontmatter(path)
        if not _is_ingestion_event_page(path, values):
            continue
        events_total += 1
        consolidated = _list_values(values.get("consolidated_into"))
        if not consolidated:
            events_without_consolidated_into.append(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        if "affected_pages:" in text and "impact_closure:" not in text:
            events_without_impact_closure.append(rel)

    coverage = operational_coverage(
        root, graph, config.contexts, default_context=config.default_context
    )

    return {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "repo_id": config.repo_id,
        "memory_root": config.paths["memory_root"],
        "summary": {
            "pages_total": len(pages),
            "page_types": dict(sorted(by_type.items())),
            "contexts": dict(sorted(by_context.items())),
            "low_information_density_pages": len(low_density_pages),
            "thin_link_pages": len(thin_link_pages),
            "repeated_blocks": len(repeated_blocks),
            "bad_repetition_blocks": len(bad_repetition),
            "ingestion_events": events_total,
            "events_without_consolidated_into": len(events_without_consolidated_into),
            "events_without_impact_closure": len(events_without_impact_closure),
            "quality_exempt_pages": len(quality_exempt_pages),
            "quality_exemption_missing_reason": len(quality_exemption_missing_reason),
            "responsibilities_without_action": len(coverage["responsibilities_without_action"]),
            "contexts_without_role": len(coverage["contexts_without_role"]),
            "orphan_actions": len(coverage["orphan_actions"]),
            "role_responsibility_edge_mismatch": len(coverage["role_responsibility_edge_mismatch"]),
            "chunk_sources": len(chunk_payloads),
            "chunks_total": total_chunks,
            "estimated_context_tokens": total_tokens,
            "cached_calls": cached_calls,
            "pending_calls": pending_calls,
            "cache_reuse_rate": round(cached_calls / max(total_chunks, 1), 4),
        },
        "cost_telemetry": {
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "model_profile": model_profile,
            "source_costs": source_costs,
            "note": "Telemetry only. v6.3 does not enforce a hard budget.",
        },
        "quality_flags": {
            "low_information_density_pages": low_density_pages,
            "thin_link_pages": thin_link_pages,
            "bad_repetition_blocks": bad_repetition,
            "repeated_blocks": repeated_blocks,
            "events_without_consolidated_into": events_without_consolidated_into,
            "events_without_impact_closure": events_without_impact_closure,
            "quality_exempt_pages": quality_exempt_pages,
            "quality_exemption_missing_reason": quality_exemption_missing_reason,
            "responsibilities_without_action": coverage["responsibilities_without_action"],
            "contexts_without_role": coverage["contexts_without_role"],
            "orphan_actions": coverage["orphan_actions"],
            "role_responsibility_edge_mismatch": coverage["role_responsibility_edge_mismatch"],
        },
        "pages": pages,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    cost = report["cost_telemetry"]
    lines = [
        "# Wiki quality and cost report",
        "",
        f"Schema: `{report['schema_version']}`.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "pages_total",
        "low_information_density_pages",
        "thin_link_pages",
        "repeated_blocks",
        "bad_repetition_blocks",
        "ingestion_events",
        "events_without_consolidated_into",
        "events_without_impact_closure",
        "quality_exempt_pages",
        "quality_exemption_missing_reason",
        "responsibilities_without_action",
        "contexts_without_role",
        "orphan_actions",
        "role_responsibility_edge_mismatch",
        "chunk_sources",
        "chunks_total",
        "estimated_context_tokens",
        "cached_calls",
        "pending_calls",
        "cache_reuse_rate",
    ):
        lines.append(f"| `{key}` | {summary[key]} |")

    lines.extend(
        [
            "",
            "## Cost Telemetry",
            "",
            f"- Prompt version: `{cost['prompt_version']}`.",
            f"- Schema version: `{cost['schema_version']}`.",
            f"- Model profile: `{cost['model_profile']}`.",
            "- Cost is measured for control and comparison; v6.3 does not enforce a hard budget.",
            "",
            "| Source | Chunks | Estimated tokens | Cached | Pending |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for source in cost["source_costs"]:
        source_id = source["source_id"] or "(unknown)"
        lines.append(
            f"| `{source_id}` | {source['chunks']} | {source['estimated_tokens']} | "
            f"{source['cached_calls']} | {source['pending_calls']} |"
        )
    if not cost["source_costs"]:
        lines.append("| _(none)_ | 0 | 0 | 0 | 0 |")

    flags = report["quality_flags"]
    lines.extend(["", "## Quality Flags", ""])
    for title, key in (
        ("Low information density pages", "low_information_density_pages"),
        ("Thin link pages", "thin_link_pages"),
        ("Events without consolidated_into", "events_without_consolidated_into"),
        ("Events without impact_closure", "events_without_impact_closure"),
        ("Quality exemptions missing reason", "quality_exemption_missing_reason"),
    ):
        lines.extend([f"### {title}", ""])
        values = flags[key]
        if values:
            lines.extend(f"- `{value}`" for value in values[:50])
        else:
            lines.append("- None.")
        lines.append("")

    lines.extend(["### Operational model coverage", ""])
    for title, key in (
        ("Responsibilities without action", "responsibilities_without_action"),
        ("Contexts without role", "contexts_without_role"),
        ("Orphan actions", "orphan_actions"),
    ):
        lines.extend([f"#### {title}", ""])
        values = flags[key]
        if values:
            lines.extend(f"- `{value}`" for value in values[:50])
        else:
            lines.append("- None.")
        lines.append("")
    lines.extend(["#### Role/responsibility edge mismatch", ""])
    if flags["role_responsibility_edge_mismatch"]:
        for item in flags["role_responsibility_edge_mismatch"][:50]:
            lines.append(f"- `{item['role']}` <-> `{item['responsibility']}`")
    else:
        lines.append("- None.")
    lines.append("")

    lines.extend(["### Bad repetition blocks", ""])
    if flags["bad_repetition_blocks"]:
        for item in flags["bad_repetition_blocks"][:20]:
            pages = ", ".join(f"`{page}`" for page in item["pages"])
            lines.append(f"- {item['text_preview']}... ({pages})")
    else:
        lines.append("- None.")
    lines.extend(["", "### Quality exempt pages", ""])
    if flags["quality_exempt_pages"]:
        for item in flags["quality_exempt_pages"][:50]:
            lines.append(
                f"- `{item['path']}` ({item['exemptions']}): {item['reason'] or 'missing reason'}"
            )
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)
