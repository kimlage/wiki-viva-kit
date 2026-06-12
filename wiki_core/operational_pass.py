from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import WikiConfig, freshness_for
from .paths import WikiPaths

H1_RE = re.compile(r"^#\s+(.*\S)\s*$")
STATE_PREFIX_RE = re.compile(r"^(?:Estado|State):\s*(.+?)\s*$", re.I)
TITLE_PREFIX_RE = re.compile(r"^(?:Decisao|Decision|Acao|Action|Claim|Fonte|Source)\s*-\s*", re.I)
ATTENTION_RE = re.compile(
    r"\b("
    r"pending|blocked|blocker|stale|partial|unread|incomplete|unknown|gap|risk|"
    r"pendente|bloquead[oa]?|stale|parcial|incomplet[oa]?|incerteza|problema|"
    r"contradicao|contradicao|risco|vencid[oa]?|sem evidencia"
    r")\b",
    re.I,
)


@dataclass(frozen=True)
class PageRecord:
    path: Path
    rel: str
    page_id: str
    page_type: str
    title: str
    context: str
    updated_at: str
    stale_after_days: str
    status: str
    source_refs: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


@dataclass(frozen=True)
class SourceRow:
    page: PageRecord
    source_type: str
    ingestion_state: str
    last_update: str
    next_refresh: str
    refresh_status: str
    refresh_policy: str


@dataclass(frozen=True)
class ContextRow:
    context: str
    hub: PageRecord | None
    vitality: str
    sources: int
    source_attention: int
    actions: int
    action_attention: int
    claims: int
    decisions: int
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class AttentionRow:
    context: str
    page: PageRecord
    reason: str


@dataclass(frozen=True)
class OperationalPassReport:
    context_rows: tuple[ContextRow, ...]
    sources: tuple[SourceRow, ...]
    actions: tuple[PageRecord, ...]
    decisions: tuple[PageRecord, ...]
    pending_decisions: tuple[PageRecord, ...]
    claims: tuple[PageRecord, ...]
    attention: tuple[AttentionRow, ...]
    pending_ids: tuple[str, ...]


def read_markdown_page(path: Path, root: Path, default_context: str) -> PageRecord:
    text = path.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            try:
                frontmatter = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                frontmatter = {}
            body = text[text.find("\n", end + 4) + 1 :]
    rel = path.relative_to(root).as_posix()
    page_id = str(frontmatter.get("page_id") or path.stem)
    page_type = str(frontmatter.get("page_type") or "")
    title = _clean_title(str(frontmatter.get("title") or first_h1(body) or path.stem))
    context = str(frontmatter.get("context") or default_context)
    status = str(frontmatter.get("status") or first_state(body) or "").strip()
    return PageRecord(
        path=path,
        rel=rel,
        page_id=page_id,
        page_type=page_type,
        title=title,
        context=context,
        updated_at=_date_text(frontmatter.get("updated_at")),
        stale_after_days=str(frontmatter.get("stale_after_days") or ""),
        status=status,
        source_refs=_string_tuple(frontmatter.get("source_refs")),
        claims=_string_tuple(frontmatter.get("claims")),
        decisions=_string_tuple(frontmatter.get("decisions")),
        actions=_string_tuple(frontmatter.get("actions")),
        evidence_refs=_string_tuple(frontmatter.get("evidence_refs")),
        frontmatter=frontmatter,
        body=body,
    )


def collect_pages(root: Path, config: WikiConfig) -> tuple[PageRecord, ...]:
    paths = WikiPaths(root, config)
    if not paths.memory_root.is_dir():
        return ()
    pages: list[PageRecord] = []
    for path in sorted(paths.memory_root.rglob("*.md")):
        pages.append(read_markdown_page(path, root, config.default_context))
    return tuple(pages)


def pending_action_ids(paths: WikiPaths) -> tuple[str, ...]:
    if not paths.pending_actions_file.exists():
        return ()
    ids: list[str] = []
    body_started = False
    for line in paths.pending_actions_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            body_started = True
            continue
        if not body_started:
            continue
        match = re.match(r"^\s*-\s+`?([^`\s)]+)`?", line)
        if match:
            ids.append(match.group(1).strip())
    return tuple(ids)


def build_operational_pass_report(
    root: Path,
    config: WikiConfig,
    *,
    as_of: dt.date | None = None,
    contexts: tuple[str, ...] = (),
) -> OperationalPassReport:
    paths = WikiPaths(root, config)
    as_of = as_of or dt.date.today()
    pages = collect_pages(root, config)
    pending_ids = pending_action_ids(paths)

    selected_contexts = tuple(contexts)
    if selected_contexts:
        pages = tuple(p for p in pages if p.context in selected_contexts)

    sources = tuple(
        sorted(
            (_source_row(page, as_of) for page in pages if _is_operational_source(page)),
            key=lambda row: (row.page.context, row.page.title.lower(), row.page.rel),
        )
    )
    actions = tuple(
        sorted(
            (p for p in pages if p.page_type == "action"),
            key=lambda p: (_pending_rank(p, pending_ids), p.context, p.title.lower(), p.rel),
        )
    )
    decisions = tuple(sorted((p for p in pages if p.page_type == "decision"), key=_page_sort_key))
    pending_decisions = tuple(d for d in decisions if _decision_needs_attention(d))
    claims = tuple(sorted((p for p in pages if p.page_type == "claim"), key=_page_sort_key))
    memory_root = str(config.paths["memory_root"]).strip("/")
    hubs: dict[str, PageRecord] = {}
    for page in pages:
        if page.rel == f"{memory_root}/{page.context}/index.md":
            hubs[page.context] = page
        elif page.rel == f"{memory_root}/index.md" and page.context == config.default_context:
            hubs.setdefault(page.context, page)
    for page in pages:
        if page.page_type == "context_hub" and page.context not in hubs:
            hubs[page.context] = page

    operational_pages = (
        tuple(source.page for source in sources)
        + actions
        + claims
        + decisions
        + tuple(hubs.values())
    )
    context_names = _context_order(config.contexts, operational_pages, selected_contexts)
    context_rows: list[ContextRow] = []
    for context in context_names:
        ctx_sources = [s for s in sources if s.page.context == context]
        ctx_actions = [a for a in actions if a.context == context]
        ctx_claims = [c for c in claims if c.context == context]
        ctx_decisions = [d for d in decisions if d.context == context]
        hub = hubs.get(context)
        context_rows.append(
            ContextRow(
                context=context,
                hub=hub,
                vitality=_vitality(hub, as_of, config),
                sources=len(ctx_sources),
                source_attention=sum(1 for s in ctx_sources if _source_needs_attention(s)),
                actions=len(ctx_actions),
                action_attention=sum(1 for a in ctx_actions if _page_needs_attention(a)),
                claims=len(ctx_claims),
                decisions=len(ctx_decisions),
                next_steps=_next_steps(context, ctx_actions, ctx_sources, pending_ids),
            )
        )

    attention = tuple(
        sorted(
            _attention_rows(sources, actions, claims),
            key=lambda row: (row.context, row.page.page_type, row.page.title.lower(), row.page.rel),
        )
    )
    return OperationalPassReport(
        context_rows=tuple(context_rows),
        sources=sources,
        actions=actions,
        decisions=decisions,
        pending_decisions=pending_decisions,
        claims=claims,
        attention=attention,
        pending_ids=pending_ids,
    )


def build_operational_pass_page(
    root: Path,
    config: WikiConfig,
    *,
    updated_at: str | None = None,
    contexts: tuple[str, ...] = (),
) -> str:
    paths = WikiPaths(root, config)
    date = _parse_date(updated_at) or dt.date.today()
    report = build_operational_pass_report(root, config, as_of=date, contexts=contexts)
    s = _strings(config.language)
    page_dir = paths.operational_pass_page.parent
    page_id_prefix = paths.operational_pass_page.stem
    context_label = ", ".join(contexts) if contexts else s["all_contexts"]

    lines: list[str] = [
        "---",
        f"page_id: {page_id_prefix}-{config.repo_id}",
        "page_type: dashboard",
        f"context: {config.default_context}",
        f"visibility: {config.default_visibility}",
        f"updated_at: {date.isoformat()}",
        f"stale_after_days: {freshness_for(config.default_context, 'dashboard', config)}",
        "sources_policy: memorias_fontes_acoes_contextos",
        f"gate: {config.approval.get('gate', 'github_pr')}",
        "sensitive_data_policy: private_sensitive_allowed",
        f'purpose: "{s["purpose"]}"',
        "---",
        "",
        f"# {s['title']}",
        "",
        s["updated"].format(date=date.isoformat()),
        "",
        s["intro"].format(contexts=context_label),
        "",
        s["h_contexts"],
        "",
        s["th_contexts"],
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if report.context_rows:
        for row in report.context_rows:
            hub = _page_link(row.hub, page_dir) if row.hub else s["none"]
            next_steps = "<br>".join(_escape(step) for step in row.next_steps) if row.next_steps else s["none"]
            lines.append(
                f"| {_escape(row.context)} | {hub} | {s.get('vital_' + row.vitality, row.vitality)} | "
                f"{row.sources} | {row.source_attention} | {row.actions} | "
                f"{row.action_attention} | {row.claims} / {row.decisions} | {next_steps} |"
            )
    else:
        lines.append(s["empty_contexts"])

    lines += ["", s["h_sources"], "", s["th_sources"], "| --- | --- | --- | --- | --- | --- | --- |"]
    if report.sources:
        for row in report.sources:
            actions = ", ".join(f"`{a}`" for a in row.page.actions) if row.page.actions else s["none"]
            lines.append(
                f"| {_page_link(row.page, page_dir)} | {_escape(row.page.context)} | "
                f"`{_escape(row.ingestion_state or s['unknown'])}` | {_escape(row.last_update or s['none'])} | "
                f"{_escape(row.next_refresh or s['none'])} | {_escape(row.refresh_status or s['unknown'])} | {actions} |"
            )
    else:
        lines.append(s["empty_sources"])

    lines += ["", s["h_actions"], "", s["th_actions"], "| --- | --- | --- | --- | --- | --- |"]
    if report.actions:
        for action in report.actions:
            sources = ", ".join(f"`{r}`" for r in action.source_refs) if action.source_refs else s["none"]
            lines.append(
                f"| {_page_link(action, page_dir)} | {_escape(action.context)} | "
                f"`{_escape(action.status or s['unknown'])}` | {_escape(action.updated_at or s['none'])} | "
                f"{sources} | {_escape(_attention_reason(action) or s['ok'])} |"
            )
    else:
        lines.append(s["empty_actions"])

    lines += ["", s["h_decisions"], "", s["th_decisions"], "| --- | --- | --- | --- | --- | --- |"]
    if report.pending_decisions:
        for decision in report.pending_decisions:
            actions = ", ".join(f"`{a}`" for a in decision.actions) if decision.actions else s["none"]
            lines.append(
                f"| {_page_link(decision, page_dir)} | {_escape(decision.context)} | "
                f"`{_escape(decision.status or s['unknown'])}` | {_escape(decision.updated_at or s['none'])} | "
                f"{actions} | {_escape(_attention_reason(decision) or s['ok'])} |"
            )
    else:
        lines.append(s["empty_decisions"])

    lines += ["", s["h_attention"], "", s["th_attention"], "| --- | --- | --- | --- |"]
    if report.attention:
        for row in report.attention:
            lines.append(
                f"| {_escape(row.context)} | {_escape(row.page.page_type)} | "
                f"{_page_link(row.page, page_dir)} | {_escape(row.reason)} |"
            )
    else:
        lines.append(s["empty_attention"])

    lines += [
        "",
        s["h_resume"],
        "",
        _resume_line(s["root"], paths.memory_root / "index.md", paths, page_dir, s),
        _resume_line(s["operations"], paths.operation_page, paths, page_dir, s),
        _resume_line(s["source_registry"], paths.source_registry_page, paths, page_dir, s),
        _resume_line(s["pending_actions"], paths.pending_actions_file, paths, page_dir, s),
        "",
        s["generated_by"].format(script=_rel(root / "scripts" / "wiki_operational_pass.py", page_dir)),
        "",
    ]
    return "\n".join(lines)


def report_to_dict(report: OperationalPassReport) -> dict[str, Any]:
    return {
        "contexts": [
            {
                "context": r.context,
                "hub": r.hub.rel if r.hub else "",
                "vitality": r.vitality,
                "sources": r.sources,
                "source_attention": r.source_attention,
                "actions": r.actions,
                "action_attention": r.action_attention,
                "claims": r.claims,
                "decisions": r.decisions,
                "next_steps": list(r.next_steps),
            }
            for r in report.context_rows
        ],
        "sources": [
            {
                "page_id": s.page.page_id,
                "path": s.page.rel,
                "context": s.page.context,
                "ingestion_state": s.ingestion_state,
                "last_update": s.last_update,
                "next_refresh": s.next_refresh,
                "refresh_status": s.refresh_status,
            }
            for s in report.sources
        ],
        "actions": [
            {
                "page_id": a.page_id,
                "path": a.rel,
                "context": a.context,
                "status": a.status,
                "source_refs": list(a.source_refs),
            }
            for a in report.actions
        ],
        "pending_decisions": [
            {
                "page_id": d.page_id,
                "path": d.rel,
                "context": d.context,
                "status": d.status,
                "actions": list(d.actions),
            }
            for d in report.pending_decisions
        ],
        "attention": [
            {"context": a.context, "page_type": a.page.page_type, "path": a.page.rel, "reason": a.reason}
            for a in report.attention
        ],
        "pending_ids": list(report.pending_ids),
    }


def first_h1(text: str) -> str:
    for line in text.splitlines():
        match = H1_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


def first_state(text: str) -> str:
    for line in text.splitlines():
        match = STATE_PREFIX_RE.match(line.strip())
        if match:
            raw = match.group(1).strip()
            if raw.startswith("`"):
                end = raw.find("`", 1)
                if end > 1:
                    return raw[1:end].strip()
            for sep in (" — ", " -- "):
                if sep in raw:
                    raw = raw.split(sep, 1)[0].strip()
            return raw.rstrip(".").strip()
    return ""


def _source_row(page: PageRecord, as_of: dt.date) -> SourceRow:
    fm = page.frontmatter
    last_update = _date_text(fm.get("last_ingested_at")) or page.updated_at
    next_refresh = _next_refresh(fm, last_update)
    status = _refresh_status(next_refresh, as_of)
    policy = str(fm.get("refresh_policy") or "")
    cadence = str(fm.get("refresh_cadence_days") or "")
    if policy and cadence:
        policy = f"{policy} ({cadence}d)"
    elif cadence:
        policy = f"{cadence}d"
    return SourceRow(
        page=page,
        source_type=str(fm.get("source_type") or page.page_type),
        ingestion_state=str(fm.get("ingestion_state") or fm.get("structured_ingestion_state") or page.status or ""),
        last_update=last_update,
        next_refresh=next_refresh.isoformat() if next_refresh else "",
        refresh_status=status,
        refresh_policy=policy,
    )


def _is_operational_source(page: PageRecord) -> bool:
    if page.page_type == "source":
        return True
    if page.page_type != "artifact":
        return False
    fm = page.frontmatter
    return any(k in fm for k in ("source_type", "ingestion_state", "structured_ingestion_state"))


def _next_refresh(fm: dict[str, Any], last_update: str) -> dt.date | None:
    explicit = _parse_date(fm.get("next_refresh_at"))
    if explicit:
        return explicit
    last = _parse_date(last_update)
    try:
        cadence = int(str(fm.get("refresh_cadence_days") or fm.get("stale_after_days") or ""))
    except ValueError:
        cadence = 0
    if last and cadence > 0:
        return last + dt.timedelta(days=cadence)
    return None


def _refresh_status(next_refresh: dt.date | None, as_of: dt.date) -> str:
    if not next_refresh:
        return "unknown"
    if next_refresh < as_of:
        return "due"
    if next_refresh <= as_of + dt.timedelta(days=7):
        return "soon"
    return "ok"


def _source_needs_attention(row: SourceRow) -> bool:
    state = row.ingestion_state.lower()
    return row.refresh_status in {"due", "soon"} or state in {"unread", "partial", "stale", "pending"}


def _page_needs_attention(page: PageRecord) -> bool:
    haystack = " ".join((page.title, page.status, page.body[:2000]))
    return bool(ATTENTION_RE.search(haystack))


def _decision_needs_attention(page: PageRecord) -> bool:
    status = page.status.lower().strip()
    return status not in {"", "decidida", "decided", "active", "ativa"} and _page_needs_attention(page)


def _attention_rows(
    sources: tuple[SourceRow, ...],
    actions: tuple[PageRecord, ...],
    claims: tuple[PageRecord, ...],
) -> list[AttentionRow]:
    rows: list[AttentionRow] = []
    for source in sources:
        if _source_needs_attention(source):
            reason = f"source {source.ingestion_state or 'unknown'}; refresh {source.refresh_status}"
            rows.append(AttentionRow(source.page.context, source.page, reason))
    for page in (*actions, *claims):
        reason = _attention_reason(page)
        if reason:
            rows.append(AttentionRow(page.context, page, reason))
    return rows


def _attention_reason(page: PageRecord) -> str:
    if _page_needs_attention(page):
        if page.status:
            return f"Status: `{page.status}`."
        return "Attention keyword detected; see linked page."
    return ""


def _next_steps(
    context: str,
    actions: list[PageRecord],
    sources: list[SourceRow],
    pending_ids: tuple[str, ...],
) -> tuple[str, ...]:
    by_id = {a.page_id: a for a in actions}
    steps: list[str] = []
    for action_id in pending_ids:
        action = by_id.get(action_id)
        if action and action.context == context:
            steps.append(f"{action.title} ({action.status or 'state unknown'})")
        if len(steps) >= 3:
            return tuple(steps)
    for action in actions:
        if action.page_id not in pending_ids and _page_needs_attention(action):
            steps.append(f"{action.title} ({action.status or 'state unknown'})")
        if len(steps) >= 3:
            return tuple(steps)
    for source in sources:
        if _source_needs_attention(source):
            steps.append(f"refresh source: {source.page.title} ({source.refresh_status})")
        if len(steps) >= 3:
            return tuple(steps)
    return tuple(steps)


def _vitality(hub: PageRecord | None, as_of: dt.date, config: WikiConfig) -> str:
    if hub is None:
        return "missing"
    updated = _parse_date(hub.updated_at)
    try:
        stale_after = int(hub.stale_after_days or freshness_for(hub.context, hub.page_type, config))
    except ValueError:
        return "unknown"
    if not updated:
        return "unknown"
    return "stale" if updated + dt.timedelta(days=stale_after) < as_of else "fresh"


def _context_order(config_contexts: tuple[str, ...], pages: tuple[PageRecord, ...], selected: tuple[str, ...]) -> tuple[str, ...]:
    if selected:
        return selected
    seen: list[str] = []
    for context in config_contexts:
        if context and context not in seen:
            seen.append(context)
    for page in pages:
        if page.context and page.context not in seen:
            seen.append(page.context)
    return tuple(seen)


def _pending_rank(page: PageRecord, pending_ids: tuple[str, ...]) -> tuple[int, str]:
    try:
        return (pending_ids.index(page.page_id), page.title.lower())
    except ValueError:
        return (len(pending_ids) + 1, page.title.lower())


def _page_sort_key(page: PageRecord) -> tuple[str, str, str]:
    return (page.context, page.title.lower(), page.rel)


def _strings(language: str) -> dict[str, str]:
    strings = {
        "pt": {
            "title": "Passagem operacional - fontes, acoes e contextos",
            "purpose": "compilacao transversal de fontes, acoes, incertezas e proximos passos por contexto",
            "updated": "Atualizado em: {date}.",
            "intro": "Compilacao deterministica para os contextos: {contexts}. Use esta pagina para comprimir proximos passos em acoes, problemas, claims, decisoes e paginas alvo; nao substitui a leitura humana das fontes vivas.",
            "all_contexts": "todos",
            "h_contexts": "## Resumo por contexto",
            "th_contexts": "| Contexto | Hub | Vitalidade | Fontes | Fontes em atencao | Acoes | Acoes em atencao | Claims / decisoes | Proximos passos |",
            "h_sources": "## Fontes por estado",
            "th_sources": "| Fonte | Contexto | Ingestao | Ultima atualizacao | Proxima revisao | Status | Acoes ligadas |",
            "h_actions": "## Acoes compiladas",
            "th_actions": "| Acao | Contexto | Estado | Atualizacao | Fontes | Sinal |",
            "h_decisions": "## Decisoes pendentes",
            "th_decisions": "| Decisao | Contexto | Estado | Atualizacao | Acoes ligadas | Sinal |",
            "h_attention": "## Problemas e incertezas",
            "th_attention": "| Contexto | Tipo | Pagina | Motivo |",
            "h_resume": "## Links de retomada",
            "root": "Indice",
            "operations": "Operacao",
            "source_registry": "Registro de fontes",
            "pending_actions": "Acoes pendentes",
            "generated_by": "Gerado por [scripts/wiki_operational_pass.py]({script}); rode `--write` para atualizar e `--check` antes do PR.",
            "none": "-",
            "unknown": "desconhecido",
            "ok": "ok",
            "vital_fresh": "fresca",
            "vital_stale": "stale",
            "vital_missing": "sem hub",
            "vital_unknown": "indeterminada",
            "empty_contexts": "| Sem contextos encontrados. | - | - | - | - | - | - | - | - |",
            "empty_sources": "| Sem fontes registradas. | - | - | - | - | - | - |",
            "empty_actions": "| Sem acoes registradas. | - | - | - | - | - |",
            "empty_decisions": "| Sem decisoes pendentes detectadas. | - | - | - | - | - |",
            "empty_attention": "| Sem problemas ou incertezas detectados por heuristica. | - | - | - |",
        },
        "en": {
            "title": "Operational pass - sources, actions and contexts",
            "purpose": "cross-context compilation of sources, actions, uncertainty and next steps",
            "updated": "Updated at: {date}.",
            "intro": "Deterministic compilation for contexts: {contexts}. Use this page to compress next steps into actions, problems, claims, decisions and target pages; it does not replace human reading of live sources.",
            "all_contexts": "all",
            "h_contexts": "## Context summary",
            "th_contexts": "| Context | Hub | Vitality | Sources | Sources needing attention | Actions | Actions needing attention | Claims / decisions | Next steps |",
            "h_sources": "## Sources by state",
            "th_sources": "| Source | Context | Ingestion | Last update | Next refresh | Status | Linked actions |",
            "h_actions": "## Compiled actions",
            "th_actions": "| Action | Context | State | Updated | Sources | Signal |",
            "h_decisions": "## Pending decisions",
            "th_decisions": "| Decision | Context | State | Updated | Linked actions | Signal |",
            "h_attention": "## Problems and uncertainty",
            "th_attention": "| Context | Type | Page | Reason |",
            "h_resume": "## Resume links",
            "root": "Index",
            "operations": "Operations",
            "source_registry": "Source registry",
            "pending_actions": "Pending actions",
            "generated_by": "Generated by [scripts/wiki_operational_pass.py]({script}); run `--write` to update and `--check` before the PR.",
            "none": "-",
            "unknown": "unknown",
            "ok": "ok",
            "vital_fresh": "fresh",
            "vital_stale": "stale",
            "vital_missing": "missing hub",
            "vital_unknown": "unknown",
            "empty_contexts": "| No contexts found. | - | - | - | - | - | - | - | - |",
            "empty_sources": "| No sources recorded. | - | - | - | - | - | - |",
            "empty_actions": "| No actions recorded. | - | - | - | - | - |",
            "empty_decisions": "| No pending decisions detected. | - | - | - | - | - |",
            "empty_attention": "| No heuristic problems or uncertainty detected. | - | - | - |",
        },
    }
    return strings.get(language, strings["en"])


def _clean_title(title: str) -> str:
    title = TITLE_PREFIX_RE.sub("", title)
    title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
    return title.strip().strip('"')


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _date_text(value: Any) -> str:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return str(value or "").strip()


def _parse_date(value: Any) -> dt.date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _rel(path: Path, page_dir: Path) -> str:
    return os.path.relpath(path, page_dir).replace(os.sep, "/")


def _page_link(page: PageRecord | None, page_dir: Path) -> str:
    if page is None:
        return "-"
    return f"[{_escape(page.title or page.page_id)}]({_rel(page.path, page_dir)})"


def _resume_line(label: str, path: Path, paths: WikiPaths, page_dir: Path, s: dict[str, str]) -> str:
    if not path.exists():
        return f"- {label}: {s['none']}"
    return f"- {label}: [{paths.rel(path)}]({_rel(path, page_dir)})"


def _escape(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()
