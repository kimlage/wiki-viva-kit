"""Consolidation: turn recorded deep-read results into wiki integration.

This is the missing half of ingestion. The deterministic pipeline gathers and
the agent deep-reads; consolidation takes the RECORDED results (llm-cache) and
scaffolds the integration so the agent updates the wiki's CONCEPTS — instead of
the source being merely cataloged:

- aggregate_results: merge the per-chunk results of one source (quadrants,
  claims, decisions, actions, risks, uncertainties, relationships, entities).
- build_event_markdown: generate the normalized EVENT page from the aggregate
  (quadrants filled from the deep read — never placeholders), with
  `consolidated_into: []` for the agent to close during integration.
- build_packet: the INTEGRATION packet — for each claim/entity, the related
  existing pages (FTS + page catalog), overlapping claims and potential
  conflicts, so the agent integrates with context instead of re-reading the
  whole wiki. Judgment stays with the agent; this only narrows candidates.
- pending_consolidations: sources whose deep read is complete but whose event
  is missing or whose consolidation is not closed (consumed by the CLI --check,
  the CI and the cockpit).

No LLM client here: deterministic scaffolding only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import yaml

from wiki_core.config import WikiConfig, freshness_for
from wiki_core.index.sqlite import sanitize_fts_query, search
from wiki_core.llm.context_pass import read_result
from wiki_core.paths import WikiPaths

REQUEST_SUFFIX = "-llm-context-request.json"
PACKET_SUFFIX = "-integration-packet.json"
PACKET_SCHEMA_VERSION = "wiki_integration_packet.v2"

# Output strings per language (generated event; drives config.language).
CONSOLIDATE_STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "event_title": "# Evento - {name}",
        "h_source": "## Fonte",
        "row_source_page": "- Fonte canonica: [{label}]({href}).",
        "row_source_id": "- source_id: `{source_id}`.",
        "row_generated": "- Evento gerado da leitura profunda gravada (llm-cache) por [scripts/wiki_consolidate.py]({script}); revisar e INTEGRAR antes de consolidar.",
        "h_quadrants": "## Quadrantes",
        "th_quadrants": "| Quadrante | Conteudo extraido | Ausencia/limite |",
        "q_ii": "Interior individual",
        "q_ei": "Exterior individual",
        "q_ic": "Interior coletivo",
        "q_ec": "Exterior coletivo",
        "h_claims": "## Claims candidatos",
        "h_decisions": "## Decisoes candidatas",
        "h_actions": "## Acoes candidatas",
        "h_risks": "## Riscos",
        "h_conflicts": "## Conflitos e ambiguidades",
        "conflicts_note": "Incertezas da leitura profunda; complete com os conflitos do pacote de integracao e registre a resolucao.",
        "h_relationships": "## Relacoes extraidas",
        "th_relationships": "| De | Para | Relacao |",
        "h_integration": "## Integracao",
        "integration_note": "Preencha `consolidated_into:` no frontmatter com as paginas ATUALIZADAS por esta ingestao (cada uma deve referenciar a fonte em `source_refs:`). Catalogar a fonte NAO e ingerir.",
        "empty": "- (nenhum)",
    },
    "en": {
        "event_title": "# Event - {name}",
        "h_source": "## Source",
        "row_source_page": "- Canonical source: [{label}]({href}).",
        "row_source_id": "- source_id: `{source_id}`.",
        "row_generated": "- Event generated from the recorded deep read (llm-cache) by [scripts/wiki_consolidate.py]({script}); review and INTEGRATE before consolidating.",
        "h_quadrants": "## Quadrants",
        "th_quadrants": "| Quadrant | Extracted content | Absence/limit |",
        "q_ii": "Interior individual",
        "q_ei": "Exterior individual",
        "q_ic": "Interior collective",
        "q_ec": "Exterior collective",
        "h_claims": "## Candidate claims",
        "h_decisions": "## Candidate decisions",
        "h_actions": "## Candidate actions",
        "h_risks": "## Risks",
        "h_conflicts": "## Conflicts and ambiguities",
        "conflicts_note": "Uncertainties from the deep read; complete with the integration packet's conflicts and record the resolution.",
        "h_relationships": "## Extracted relationships",
        "th_relationships": "| From | To | Relationship |",
        "h_integration": "## Integration",
        "integration_note": "Fill `consolidated_into:` in the frontmatter with the pages UPDATED by this ingestion (each must reference the source in `source_refs:`). Cataloging the source is NOT ingesting.",
        "empty": "- (none)",
    },
}

QUADRANT_KEYS = (
    "interior_individual",
    "exterior_individual",
    "interior_collective",
    "exterior_collective",
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]{3,}")
# Generic words excluded from the keyword-overlap heuristic (pt+en).
_STOPWORDS = {
    "para", "como", "deve", "devem", "with", "that", "this", "from", "have",
    "sobre", "entre", "quando", "where", "which", "their",
    "fonte", "source", "wiki", "pagina", "page", "memoria", "memory",
}


def _strings(language: str) -> dict[str, str]:
    return CONSOLIDATE_STRINGS.get(language, CONSOLIDATE_STRINGS["en"])


def _read_frontmatter(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_requests(paths: WikiPaths) -> list[dict[str, object]]:
    """Emitted context requests (skips ad-hoc query- packets)."""
    out: list[dict[str, object]] = []
    events_dir = paths.extraction_events
    if not events_dir.is_dir():
        return out
    for req_file in sorted(events_dir.glob(f"*{REQUEST_SUFFIX}")):
        try:
            request = json.loads(req_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_id = str(request.get("source_id") or "")
        if not source_id or source_id.startswith("query-"):
            continue
        out.append(request)
    return out


def deep_read_complete(request: dict[str, object], cache_dir: Path) -> bool:
    chunks = request.get("chunks") or []
    if not isinstance(chunks, list) or not chunks:
        return False
    for row in chunks:
        key = str(row.get("cache_key") or "")
        if not key or read_result(cache_dir, key) is None:
            return False
    return True


def _merge_quadrant(values: list[str]) -> str:
    """Join non-absent chunk texts; if every chunk marked absence, keep the note."""
    real = [v.strip() for v in values if v.strip() and not v.strip().lower().startswith("absent")]
    if real:
        seen: list[str] = []
        for value in real:
            if value not in seen:
                seen.append(value)
        return " ".join(seen)
    for value in values:
        if value.strip():
            return value.strip()
    return ""


def _dedup(items: list[object]) -> list[object]:
    seen: list[object] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def aggregate_results(request: dict[str, object], cache_dir: Path) -> dict[str, object]:
    """Merge the per-chunk deep-read results of one source (order = chunk order)."""
    quadrants: dict[str, list[str]] = {key: [] for key in QUADRANT_KEYS}
    confidence: dict[str, str] = {}
    lists: dict[str, list[object]] = {
        "claims": [], "decisions": [], "actions": [], "risks": [],
        "uncertainties": [], "relationships": [], "entities": [],
    }
    rank = {"low": 0, "medium": 1, "high": 2}
    for row in request.get("chunks") or []:
        result = read_result(cache_dir, str(row.get("cache_key") or ""))
        if not result:
            continue
        q = result.get("quadrants")
        if isinstance(q, dict):
            for key in QUADRANT_KEYS:
                quadrants[key].append(str(q.get(key) or ""))
        qc = result.get("quadrant_confidence")
        if isinstance(qc, dict):
            for key in QUADRANT_KEYS:
                value = str(qc.get(key) or "").lower()
                if value in rank:
                    prev = confidence.get(key)
                    if prev is None or rank[value] < rank[prev]:
                        confidence[key] = value  # keep the WORST (honest floor)
        for name in lists:
            value = result.get(name)
            if isinstance(value, list):
                lists[name].extend(value)
    return {
        "source_id": request.get("source_id"),
        "prompt_version": request.get("prompt_version"),
        "chunk_count": len(request.get("chunks") or []),
        "quadrants": {key: _merge_quadrant(values) for key, values in quadrants.items()},
        "quadrant_confidence": confidence,
        **{name: _dedup(values) for name, values in lists.items()},
    }


def _source_slug(source_id: str) -> str:
    """source-<name>-<digest12> -> <name>; tolerate non-canonical ids."""
    value = str(source_id)
    if value.startswith("source-"):
        value = value[len("source-"):]
    parts = value.rsplit("-", 1)
    if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{8,64}", parts[1]):
        value = parts[0]
    return value or "source"


def _claim_text(claim: object) -> str:
    if isinstance(claim, dict):
        return str(claim.get("claim") or claim.get("text") or "")
    return str(claim)


def _entity_name(entity: object) -> str:
    if isinstance(entity, dict):
        return str(entity.get("name") or "")
    return str(entity)


def build_event_markdown(
    aggregated: dict[str, object],
    *,
    config: WikiConfig,
    context: str,
    date: dt.date,
    source_page: str | None = None,
    source_ref: str | None = None,
    source_type: str = "file",
    risk_level: str = "medium",
    event_dir: Path | None = None,
    root: Path | None = None,
    impact: dict[str, object] | None = None,
) -> str:
    """The normalized event, generated from the recorded deep read."""
    s = _strings(config.language)
    source_id = str(aggregated.get("source_id") or "source")
    slug = _source_slug(source_id)
    name = f"{date.isoformat()}-{slug}"
    quadrants = aggregated.get("quadrants") or {}
    confidence = aggregated.get("quadrant_confidence") or {}
    impact = impact or {}
    must_update = [str(p) for p in impact.get("must_update") or []]
    should_review = [str(p) for p in impact.get("should_review") or []]

    def q_row(label: str, key: str) -> str:
        content = str(quadrants.get(key) or "").replace("|", "\\|").replace("\n", " ").strip()
        absent = ""
        if content.lower().startswith("absent"):
            absent, content = content, ""
        conf = confidence.get(key)
        if conf and content:
            content = f"{content} (confidence: {conf})"
        return f"| {label} | {content} | {absent} |"

    def bullet_list(name_: str) -> list[str]:
        items = aggregated.get(name_) or []
        rows: list[str] = []
        for item in items:
            text = _claim_text(item) if name_ == "claims" else (
                str(item.get("decision") or item.get("action") or item) if isinstance(item, dict) else str(item)
            )
            text = text.strip()
            if text:
                rows.append(f"- {text}")
        return rows or [s["empty"]]

    rel_rows: list[str] = []
    for rel in aggregated.get("relationships") or []:
        if isinstance(rel, dict):
            frm = str(rel.get("from") or "").replace("|", "\\|")
            to = str(rel.get("to") or "").replace("|", "\\|")
            kind = str(rel.get("kind") or "").replace("|", "\\|")
            if frm or to:
                rel_rows.append(f"| {frm} | {to} | {kind} |")

    script_href = "../../../../scripts/wiki_consolidate.py"
    source_rows: list[str] = []
    if source_page and root is not None and event_dir is not None:
        import os

        href = os.path.relpath(root / source_page, event_dir).replace(os.sep, "/")
        source_rows.append(s["row_source_page"].format(label=source_page, href=href))
    source_rows.append(s["row_source_id"].format(source_id=source_id))
    source_rows.append(s["row_generated"].format(script=script_href))

    fm: list[str] = [
        "---",
        f"event_id: evt-{name}",
        f"page_id: evento-{name}" if config.language == "pt" else f"page_id: event-{name}",
        "page_type: source_catalog",
        f"context: {context}",
        "visibility: private_self",
        f"updated_at: {date.isoformat()}",
        f"stale_after_days: {freshness_for(context, 'source_catalog', config)}",
        "sources_policy: evento_normalizado_com_quadrantes",
        "gate: github_pr",
        "sensitive_data_policy: private_sensitive_allowed",
        f"source_id: {source_id}",
    ]
    if source_ref:
        fm.append(f"source_ref: {source_ref}")
    fm.extend(
        [
            f"source_type: {source_type}",
            f"captured_at: {date.isoformat()}",
            f"verified_at: {date.isoformat()}",
            "status_epistemologico: proposta",
            f"risk_level: {risk_level}",
            "requires_gate: true",
            "target_pages: []",
            "consolidated_into: []",
        ]
    )
    if must_update or should_review:
        fm.append("affected_pages:")
        if must_update:
            fm.append("  must_update:")
            fm.extend(f"    - {page}" for page in must_update)
        else:
            fm.append("  must_update: []")
        if should_review:
            fm.append("  should_review:")
            fm.extend(f"    - {page}" for page in should_review)
        else:
            fm.append("  should_review: []")
    else:
        fm.append("affected_pages: {must_update: [], should_review: []}")
    fm.extend(
        [
            "impact_closure:",
            "  updated: []",
            "  no_change: []",
            "  blocked: []",
            "---",
        ]
    )

    uncertainties = [str(u).strip() for u in (aggregated.get("uncertainties") or []) if str(u).strip()]
    body: list[str] = [
        *fm,
        "",
        s["event_title"].format(name=slug),
        "",
        s["h_source"],
        "",
        *source_rows,
        "",
        s["h_quadrants"],
        "",
        s["th_quadrants"],
        "| --- | --- | --- |",
        q_row(s["q_ii"], "interior_individual"),
        q_row(s["q_ei"], "exterior_individual"),
        q_row(s["q_ic"], "interior_collective"),
        q_row(s["q_ec"], "exterior_collective"),
        "",
        s["h_claims"],
        "",
        *bullet_list("claims"),
        "",
        s["h_decisions"],
        "",
        *bullet_list("decisions"),
        "",
        s["h_actions"],
        "",
        *bullet_list("actions"),
        "",
        s["h_risks"],
        "",
        *bullet_list("risks"),
        "",
        s["h_conflicts"],
        "",
        s["conflicts_note"],
        "",
        *([f"- {u}" for u in uncertainties] or [s["empty"]]),
        "",
    ]
    if rel_rows:
        body.extend([s["h_relationships"], "", s["th_relationships"], "| --- | --- | --- |", *rel_rows, ""])
    body.extend([s["h_integration"], "", s["integration_note"], ""])
    return "\n".join(body)


def _page_catalog(root: Path, config: WikiConfig) -> dict[str, dict[str, object]]:
    """page_id -> {rel, title, aliases, page_type, source_refs} for memory pages."""
    memory_root = root / config.paths["memory_root"]
    catalog: dict[str, dict[str, object]] = {}
    if not memory_root.is_dir():
        return catalog
    for md in sorted(memory_root.rglob("*.md")):
        fm = _read_frontmatter(md)
        page_id = str(fm.get("page_id") or "")
        if not page_id:
            continue
        aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
        catalog[page_id] = {
            "rel": md.relative_to(root).as_posix(),
            "title": str(fm.get("title") or ""),
            "aliases": [str(a) for a in aliases],
            "page_type": str(fm.get("page_type") or ""),
            "source_refs": [str(x) for x in fm.get("source_refs") or []] if isinstance(fm.get("source_refs"), list) else [],
        }
    return catalog


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def build_packet(
    aggregated: dict[str, object], root: Path, config: WikiConfig, paths: WikiPaths
) -> dict[str, object]:
    """Integration packet: candidate targets and overlaps for the agent."""
    catalog = _page_catalog(root, config)
    db_path = paths.indexes / "wiki.sqlite"

    def fts(query: str, limit: int = 3) -> list[dict[str, object]]:
        if not db_path.exists() or not query.strip():
            return []
        try:
            hits = search(db_path, sanitize_fts_query(query), limit=limit)
        except Exception:
            return []
        return [
            {"source_id": h.get("source_id"), "chunk_id": h.get("chunk_id"),
             "excerpt": str(h.get("text") or "")[:240]}
            for h in hits
        ]

    # Entity -> page candidates (exact name/alias containment, case-insensitive).
    entity_matches: list[dict[str, object]] = []
    for entity in aggregated.get("entities") or []:
        name = _entity_name(entity).strip()
        if len(name) < 4:
            continue
        low = name.lower()
        pages = [
            {"page_id": pid, "rel": meta["rel"]}
            for pid, meta in catalog.items()
            if low in str(meta["title"]).lower()
            or any(low == str(a).lower() for a in meta["aliases"])
            or low.replace(" ", "-") in pid
        ]
        entity_matches.append({"entity": name, "pages": pages})

    # Claim -> related content (FTS over sources+pages) + overlapping claim pages.
    claim_pages = {pid: meta for pid, meta in catalog.items() if meta["page_type"] == "claim"}
    claim_rows: list[dict[str, object]] = []
    for claim in aggregated.get("claims") or []:
        text = _claim_text(claim).strip()
        if not text:
            continue
        kw = _keywords(text)
        overlaps = [
            {"page_id": pid, "rel": meta["rel"],
             "shared_keywords": sorted(kw & _keywords(str(meta["title"])))}
            for pid, meta in claim_pages.items()
            if len(kw & _keywords(str(meta["title"]))) >= 2
        ]
        claim_rows.append(
            {
                "claim": text,
                "related": fts(text),
                "overlapping_claims": overlaps,
                "potential_conflict": bool(overlaps),
            }
        )

    should_review = sorted(
        {
            str(page["rel"])
            for row in entity_matches
            for page in row.get("pages", [])
            if isinstance(page, dict) and page.get("rel")
        }
        | {
            str(page["rel"])
            for row in claim_rows
            for page in row.get("overlapping_claims", [])
            if isinstance(page, dict) and page.get("rel")
        }
    )
    must_update = sorted(
        {
            str(meta["rel"])
            for meta in catalog.values()
            if str(aggregated.get("source_id") or "") in (meta.get("source_refs") or [])
        }
    )

    return {
        "kind": "wiki_integration_packet",
        "schema_version": PACKET_SCHEMA_VERSION,
        "source_id": aggregated.get("source_id"),
        "impact": {
            "must_update": must_update,
            "should_review": [page for page in should_review if page not in must_update],
        },
        "claims": claim_rows,
        "entities": entity_matches,
        "uncertainties": aggregated.get("uncertainties") or [],
        "relationships": aggregated.get("relationships") or [],
        "instructions": (
            "Integrate: update the candidate target pages (hubs/concepts) with the new "
            "information; create/update load-bearing claim pages (conflict fields when "
            "they collide); resolve or record each potential_conflict and uncertainty; "
            "then fill the event's consolidated_into with the pages you updated (each "
            "must reference the source in source_refs)."
        ),
    }


def find_event_for_source(paths: WikiPaths, source_id: str) -> Path | None:
    events_dir = paths.ingest_events_dir
    if not events_dir.is_dir():
        return None
    for md in sorted(events_dir.glob("*.md")):
        if md.name == "README.md":
            continue
        fm = _read_frontmatter(md)
        if str(fm.get("source_id") or "") == source_id:
            return md
    return None


def pending_consolidations(root: Path, config: WikiConfig) -> list[dict[str, object]]:
    """Sources with a COMPLETE deep read whose consolidation is not closed.

    States reported: missing_event (no event references the source_id) and
    missing_consolidated_into (event exists but integration not closed).
    """
    paths = WikiPaths(root, config)
    cache_dir = paths.llm_cache
    out: list[dict[str, object]] = []
    for request in load_requests(paths):
        source_id = str(request.get("source_id"))
        if not deep_read_complete(request, cache_dir):
            continue  # the context-pass gate already covers incomplete reads
        event = find_event_for_source(paths, source_id)
        if event is None:
            out.append({"source_id": source_id, "state": "missing_event"})
            continue
        fm = _read_frontmatter(event)
        consolidated = fm.get("consolidated_into")
        if not isinstance(consolidated, list) or not consolidated:
            out.append(
                {
                    "source_id": source_id,
                    "state": "missing_consolidated_into",
                    "event": event.relative_to(root).as_posix(),
                }
            )
    return out
