"""Insight job implementation (Information -> Insight).

Deterministic flow:

    score events + indexed chunks + memory pages (per theme)
        -> context PACKET (request) + PROPOSAL skeleton
        -> [repo agent synthesizes] -> [human promotes via PR]

Honesty: the job never writes canonical memory. It only writes DERIVED artifacts
(gitignored) and returns their path. The intelligence (synthesizing the insight)
lives in the agent, via a skill; promotion to memory goes through a PR (gate).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.detectors import scan_text
from wiki_core.ids import sha256_text
from wiki_core.index.sqlite import search
from wiki_core.paths import WikiPaths
from wiki_core.score import compute_karma, load_events

SCHEMA_VERSION = "wiki_insight_job.v1"

# Fields that the agent-produced insight PROPOSAL must fill in.
INSIGHT_PROPOSAL_FIELDS = [
    "title",
    "reading",          # the reading/insight in one sentence
    "evidence",         # list of evidence items (chunk_id/page/event)
    "uncertainty",      # what is still unknown
    "possible_action",  # possible action, if any
    "status_epistemologico",  # always "candidato" until the human gate
]


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "tema"


@dataclass(frozen=True)
class InsightJobResult:
    theme: str
    context: str
    job_id: str
    event_count: int
    chunk_count: int
    page_count: int
    karma_total: float
    packet_path: str | None
    proposal_path: str | None
    wrote: bool

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _gather_events(paths: WikiPaths, context: str) -> tuple[list[dict[str, object]], float]:
    events = load_events(paths.derived_root / "score-events.jsonl")
    scoped = [e for e in events if e.context == context] if context else events
    karma = compute_karma(scoped) if scoped else {"total": 0.0}
    rows = [
        {"event_type": e.event_type, "dimensao": e.dimensao, "context": e.context, "ts": e.ts}
        for e in scoped[-20:]
    ]
    total = float(karma.get("total", 0.0))
    return rows, total


def _gather_chunks(paths: WikiPaths, theme: str, limit: int) -> list[dict[str, object]]:
    hits = search(paths.indexes / "wiki.sqlite", theme, limit=limit)
    rows: list[dict[str, object]] = []
    for hit in hits:
        text = str(hit.get("text", ""))
        # Actually redacts the excerpt when there is a secret (PII is allowed in
        # private; the packet is derived). Before, the comment promised redaction
        # but the code wrote the raw text up to 500 chars — the secret leaked
        # (finding 10).
        has_secret = any(f.category == "secret" for f in scan_text(text))
        excerpt = "[excerpt omitted: credential detected in source]" if has_secret else text[:500]
        rows.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "source_id": hit.get("source_id"),
                "excerpt": excerpt,
                "has_secret": has_secret,
            }
        )
    return rows


def _gather_pages(paths: WikiPaths, theme: str, limit: int = 10) -> list[str]:
    root = paths.root
    memory_root = paths.memory_root  # configured layout, never hardcoded
    if not memory_root.exists():
        return []
    needle = theme.lower()
    hits: list[str] = []
    for path in sorted(memory_root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text.lower():
            hits.append(path.relative_to(root).as_posix())
        if len(hits) >= limit:
            break
    return hits


# Generated-OUTPUT strings per language (the insight proposal page is rendered
# in the configured language, like the cockpit and the ingestion proposal).
INSIGHT_STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "title": "# Insight (propuesta) - {theme}",
        "banner": "> PROPUESTA generada por el trabajo de insight a partir de evidencia existente. No es verdad canónica hasta que el agente la sintetice y una persona la apruebe mediante un PR.",
        "h_reading": "## Lectura",
        "fill_reading": "- Debe completarlo el agente (una frase con la idea).",
        "h_evidence": "## Evidencia reunida",
        "row_events": "- Eventos de puntuación en el contexto `{context}`: {n}.",
        "row_chunks": "- Chunks relevantes para el tema: {n}.",
        "chunk_bullet": "- `{chunk_id}` (fuente `{source_id}`)",
        "row_pages": "- Páginas de memoria que mencionan el tema: {n}.",
        "h_uncertainty": "## Incertidumbre",
        "fill_uncertainty": "- Debe completarlo el agente (qué sigue siendo desconocido).",
        "h_action": "## Acción posible",
        "fill_action": "- Debe completarlo el agente (acción posible, si corresponde).",
    },
    "pt": {
        "title": "# Insight (proposta) - {theme}",
        "banner": (
            "> PROPOSTA gerada pelo insight job a partir de evidencia ja existente. "
            "Nao e verdade canonica ate o agente sintetizar e um humano aprovar via PR."
        ),
        "h_reading": "## Leitura",
        "fill_reading": "- A preencher pelo agente (uma frase com o insight).",
        "h_evidence": "## Evidencias reunidas",
        "row_events": "- Eventos de score no contexto `{context}`: {n}.",
        "row_chunks": "- Chunks relevantes ao tema: {n}.",
        "chunk_bullet": "  - `{chunk_id}` (fonte `{source_id}`)",
        "row_pages": "- Paginas de memoria que mencionam o tema: {n}.",
        "h_uncertainty": "## Incerteza",
        "fill_uncertainty": "- A preencher pelo agente (o que ainda nao se sabe).",
        "h_action": "## Possivel acao",
        "fill_action": "- A preencher pelo agente (acao possivel, se houver).",
    },
    "en": {
        "title": "# Insight (proposal) - {theme}",
        "banner": (
            "> PROPOSAL generated by the insight job from already-existing evidence. "
            "It is not canonical truth until the agent synthesizes it and a human approves via PR."
        ),
        "h_reading": "## Reading",
        "fill_reading": "- To be filled by the agent (one sentence with the insight).",
        "h_evidence": "## Gathered evidence",
        "row_events": "- Score events in context `{context}`: {n}.",
        "row_chunks": "- Chunks relevant to the theme: {n}.",
        "chunk_bullet": "  - `{chunk_id}` (source `{source_id}`)",
        "row_pages": "- Memory pages mentioning the theme: {n}.",
        "h_uncertainty": "## Uncertainty",
        "fill_uncertainty": "- To be filled by the agent (what is still unknown).",
        "h_action": "## Possible action",
        "fill_action": "- To be filled by the agent (possible action, if any).",
    },
}


def _is(language: str) -> dict[str, str]:
    return INSIGHT_STRINGS.get(language, INSIGHT_STRINGS["en"])


def _proposal_markdown(
    theme: str, context: str, date: dt.date, events, chunks, pages, language: str = "en"
) -> str:
    s = _is(language)
    return "\n".join(
        [
            "---",
            f"page_id: insight-{date.isoformat()}-{_slugify(theme)}",
            "page_type: insight",
            f"context: {context}",
            "visibility: private_self",
            f"updated_at: {date.isoformat()}",
            "status: candidato",
            "status_epistemologico: candidato",
            "gate: github_pr",
            "sensitive_data_policy: private_sensitive_allowed",
            "---",
            "",
            s["title"].format(theme=theme),
            "",
            s["banner"],
            "",
            s["h_reading"],
            "",
            s["fill_reading"],
            "",
            s["h_evidence"],
            "",
            s["row_events"].format(context=context, n=len(events)),
            s["row_chunks"].format(n=len(chunks)),
            *[
                s["chunk_bullet"].format(chunk_id=c["chunk_id"], source_id=c["source_id"])
                for c in chunks[:8]
            ],
            s["row_pages"].format(n=len(pages)),
            *[f"  - {p}" for p in pages[:8]],
            "",
            s["h_uncertainty"],
            "",
            s["fill_uncertainty"],
            "",
            s["h_action"],
            "",
            s["fill_action"],
            "",
        ]
    )


def run(
    theme: str,
    context: str,
    root: Path,
    config: WikiConfig,
    *,
    write: bool = True,
    limit: int = 10,
    date: dt.date | None = None,
) -> InsightJobResult:
    """Gather evidence about ``theme`` and emit an insight packet + proposal.

    With ``write=False`` nothing is written (computed in memory). Never writes
    canonical memory: the artifacts go to ``data/derived/wiki/insight-jobs/``
    (gitignored).
    """
    paths = WikiPaths(root, config)
    job_id = sha256_text(f"{theme}|{context}")[:12]
    the_date = date or dt.date.today()

    events, karma_total = _gather_events(paths, context)
    chunks = _gather_chunks(paths, theme, limit)
    pages = _gather_pages(paths, theme)

    packet = {
        "schema_version": SCHEMA_VERSION,
        "kind": "insight_request",
        "job_id": job_id,
        "theme": theme,
        "context": context,
        "prompt": (
            "Synthesize ONE insight from the gathered evidence (events, chunks, "
            "pages). Produce an object with the proposal_fields. NEVER write "
            "canonical memory: fill in the PROPOSAL and let the human approve it "
            "via PR. Declare uncertainty honestly; do not invent evidence."
        ),
        "proposal_fields": INSIGHT_PROPOSAL_FIELDS,
        "evidence": {
            "score_events": events,
            "karma_total": karma_total,
            "chunks": chunks,
            "pages": pages,
        },
        "instructions": (
            "The agent running the repo reads this packet, synthesizes the insight "
            "and proposes the page (status_epistemologico=candidato) via PR. The "
            "insight job does not decide truth; it gathers signals and opens the "
            "proposal."
        ),
    }

    packet_path: str | None = None
    proposal_path: str | None = None
    if write:
        out_dir = paths.derived_root / "insight-jobs"
        out_dir.mkdir(parents=True, exist_ok=True)
        packet_file = out_dir / f"{the_date.isoformat()}-{_slugify(theme)}-{job_id}-insight-request.json"
        packet_file.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        packet_path = _rel(packet_file, root)
        proposal_file = out_dir / f"{the_date.isoformat()}-{_slugify(theme)}-{job_id}-proposal.md"
        proposal_file.write_text(
            _proposal_markdown(
                theme, context, the_date, events, chunks, pages, language=config.language
            ),
            encoding="utf-8",
        )
        proposal_path = _rel(proposal_file, root)

    return InsightJobResult(
        theme=theme,
        context=context,
        job_id=job_id,
        event_count=len(events),
        chunk_count=len(chunks),
        page_count=len(pages),
        karma_total=karma_total,
        packet_path=packet_path,
        proposal_path=proposal_path,
        wrote=write,
    )
