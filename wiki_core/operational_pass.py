from __future__ import annotations

import datetime as dt
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .action_state import (
    TERMINAL_ACTION_STATES,
    legacy_action_state_from_body,
    resolve_action_state,
)
from .config import WikiConfig, freshness_for
from .freshness import is_stale, parse_updated_date
from .paths import WikiPaths

H1_RE = re.compile(r"^#\s+(.*\S)\s*$")
NEXT_STEPS_HEADING_RE = re.compile(r"^#{2,6}\s+(?:Pr[oó]ximos passos|Next steps)\s*$", re.I)
NEXT_STEP_ITEM_RE = re.compile(r"^[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<rest>.+?)\s*$")
NEXT_STEP_TRIGGER_RE = re.compile(
    r"\s+(?:[-—]\s*)?(?:gatilho|trigger):\s*"
    r"(?P<trigger>.+?)"
    r"(?:\s+[-—]\s*(?:resultado|result):.*)?$",
    re.I,
)
NEXT_STEP_RESULT_RE = re.compile(r"\s+[-—]\s*(?:resultado|result):.*$", re.I)
STATE_PREFIX_RE = re.compile(r"^(?:Estado|State|Status):\s*(.+?)\s*$", re.I)
TITLE_PREFIX_RE = re.compile(r"^(?:Decisao|Decision|Acao|Action|Claim|Fonte|Source)\s*-\s*", re.I)
ATTENTION_RE = re.compile(
    r"\b("
    r"pending|blocked|blocker|stale|partial|unread|incomplete|unknown|gap|risk|"
    r"pendente|bloquead[oa]?|stale|parcial|incomplet[oa]?|incerteza|problema|lacuna|"
    r"contradicao|contradicao|risco|vencid[oa]?|sem evidencia"
    r")\b",
    re.I,
)
OPEN_CLAIM_QUALIFIER_RE = re.compile(
    r"\b("
    r"open risk|open gap|unresolved gap|"
    r"risco aberto|lacuna aberta|lacuna que segue aberta|"
    r"segue aberta|segue aberto|pendencia aberta|pendencias abertas|"
    r"conflito aberto|conflito mantido aberto|mantido aberto|mantida aberta"
    r")\b",
    re.I,
)
OPEN_CLAIM_BULLET_RE = re.compile(
    r"(?im)^\s*-\s*(?P<qualifier>(?:risk of|risco de)\b.*)$"
)
NEGATED_OPEN_CLAIM_PREFIX_RE = re.compile(
    r"(?:^|\b)(?:sem|no|not|without|nenhuma?|nao\s+ha|nao\s+existe)\s+$",
    re.I,
)
SHORT_TERM_LIMIT = 5
CLOSED_STATUS_SLUGS = frozenset(
    {
        "closed",
        "complete",
        "completed",
        "concluida",
        "concluido",
        "concluded",
        "done",
        "resolved",
        "resolvida",
        "resolvido",
    }
)
CLOSED_STATUS_PREFIXES = (
    "closed_at_",
    "closed_em_",
    "completed_at_",
    "completed_em_",
    "concluida_at_",
    "concluida_em_",
    "concluido_at_",
    "concluido_em_",
    "concluded_at_",
    "concluded_em_",
    "done_at_",
    "done_em_",
    "resolved_at_",
    "resolved_em_",
    "resolvida_at_",
    "resolvida_em_",
    "resolvido_at_",
    "resolvido_em_",
)
NON_PENDING_DECISION_STATUS_SLUGS = CLOSED_STATUS_SLUGS | frozenset(
    {
        "",
        "active",
        "ativa",
        "ativo",
        "decided",
        "decidida",
        "decidido",
    }
)
NON_ATTENTION_CLAIM_STATUS_SLUGS = CLOSED_STATUS_SLUGS | frozenset(
    {
        "decisao_operacional",
        "fact",
        "factual",
        "fato",
        "fato_operacional",
        "confirmed",
        "confirmada",
        "confirmado",
        "insight",
        "insight_aceita",
        "insight_aceito",
        "accepted_insight",
        "proven",
        "provada",
        "provado",
        "resolved",
        "resolvida",
        "resolvido",
        "sintese",
        "sintese_segura",
        "safe_synthesis",
    }
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
    action_state: str = ""
    action_state_raw: str = ""
    action_state_source: str = ""
    action_state_compatibility: bool = False
    action_state_warnings: tuple[str, ...] = ()
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
class ConsolidationOutputRow:
    context: str
    actions: int
    problems: int
    claims: int
    decisions: int
    context_notes: int
    non_ingested_sources: int
    signal: str


@dataclass(frozen=True)
class DecisionActionBlocker:
    decision: PageRecord
    action: PageRecord | None
    action_id: str


@dataclass(frozen=True)
class NextStep:
    text: str
    trigger: str
    done: bool


@dataclass(frozen=True)
class ResponsibilityNode:
    page: PageRecord
    open_actions: tuple[PageRecord, ...]
    next_steps: tuple[NextStep, ...]
    health: str  # "ok" | "atencao" | "sem_acao"


@dataclass(frozen=True)
class RoleNode:
    page: PageRecord
    responsibilities: tuple[ResponsibilityNode, ...]
    assignment: PageRecord | None
    health: str  # "ok" | "sem_responsabilidade"


@dataclass(frozen=True)
class OperationalModelRow:
    context: str
    roles: tuple[RoleNode, ...]
    roleless_context: bool


@dataclass(frozen=True)
class OperationalPassReport:
    context_rows: tuple[ContextRow, ...]
    consolidation_outputs: tuple[ConsolidationOutputRow, ...]
    sources: tuple[SourceRow, ...]
    actions: tuple[PageRecord, ...]
    decisions: tuple[PageRecord, ...]
    pending_decisions: tuple[PageRecord, ...]
    decision_action_blockers: tuple[DecisionActionBlocker, ...]
    claims: tuple[PageRecord, ...]
    attention: tuple[AttentionRow, ...]
    operational_model: tuple[OperationalModelRow, ...]
    pending_ids: tuple[str, ...]
    recent_pages: tuple[PageRecord, ...]


def _repo_local_target(root: Path, target: Path) -> Path:
    """Resolve a target inside ``root`` and reject traversal or symlink escape."""
    root = root.resolve(strict=False)
    candidate = target if target.is_absolute() else root / target
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"operational-pass target must stay inside repository root: {target}"
        ) from exc
    return candidate


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
    action_resolution = (
        resolve_action_state(
            frontmatter,
            legacy_state=legacy_action_state_from_body(body),
        )
        if page_type == "action"
        else None
    )
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
        action_state=action_resolution.state if action_resolution else "",
        action_state_raw=action_resolution.raw if action_resolution else "",
        action_state_source=action_resolution.source if action_resolution else "",
        action_state_compatibility=(
            action_resolution.compatibility if action_resolution else False
        ),
        action_state_warnings=(
            action_resolution.warnings if action_resolution else ()
        ),
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
    exclude_path: Path | None = None,
) -> OperationalPassReport:
    root = root.resolve(strict=False)
    paths = WikiPaths(root, config)
    as_of = as_of or dt.date.today()
    pages = collect_pages(root, config)
    pending_ids = pending_action_ids(paths)

    # Generated operational-pass pages are derived state and must not feed back
    # into their own recent-page inventory. Always exclude the configured page;
    # callers rendering to an alternate target may exclude that target as well.
    configured_target = _repo_local_target(root, paths.operational_pass_page)
    excluded_recent_paths = {paths.rel(configured_target)}
    if exclude_path is not None:
        target = _repo_local_target(root, exclude_path)
        excluded_recent_paths.add(paths.rel(target))

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
    context_notes = tuple(sorted((p for p in pages if p.page_type == "context_note"), key=_page_sort_key))
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
        + context_notes
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
                action_attention=sum(1 for a in ctx_actions if _action_needs_attention(a)),
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
    decision_action_blockers = _decision_action_blockers(pending_decisions, actions)
    operational_model = _operational_model_rows(pages, context_names)
    consolidation_outputs = _consolidation_outputs(
        context_names,
        actions,
        claims,
        decisions,
        context_notes,
        sources,
        attention,
        decision_action_blockers,
    )
    return OperationalPassReport(
        context_rows=tuple(context_rows),
        consolidation_outputs=consolidation_outputs,
        sources=sources,
        actions=actions,
        decisions=decisions,
        pending_decisions=pending_decisions,
        decision_action_blockers=decision_action_blockers,
        claims=claims,
        attention=attention,
        operational_model=operational_model,
        pending_ids=pending_ids,
        recent_pages=_recent_pages_from_pages(
            tuple(page for page in pages if page.rel not in excluded_recent_paths)
        ),
    )


def build_operational_pass_page(
    root: Path,
    config: WikiConfig,
    *,
    updated_at: str | None = None,
    contexts: tuple[str, ...] = (),
    target_path: Path | None = None,
) -> str:
    root = root.resolve(strict=False)
    paths = WikiPaths(root, config)
    target = _repo_local_target(
        root,
        target_path if target_path is not None else paths.operational_pass_page,
    )
    date = _parse_date(updated_at) or dt.date.today()
    report = build_operational_pass_report(
        root,
        config,
        as_of=date,
        contexts=contexts,
        exclude_path=target,
    )
    s = _strings(config.language)
    page_dir = target.parent
    page_id_prefix = target.stem
    context_label = ", ".join(contexts) if contexts else s["all_contexts"]

    lines: list[str] = [
        "---",
        f"page_id: {page_id_prefix}-{config.repo_id}",
        "page_type: dashboard",
        f"context: {config.default_context}",
        f"visibility: {config.default_visibility}",
        f"updated_at: {date.isoformat()}",
        "stale_after_days: 1",
        "sources_policy: memorias_fontes_acoes_contextos",
        f"gate: {config.approval.get('gate', 'github_pr')}",
        "sensitive_data_policy: private_sensitive_allowed",
        f'purpose: "{s["purpose"]}"',
        f"moc_parent: {config.paths['memory_root']}/index.md",
        "---",
        "",
        f"# {s['title']}",
        "",
        s["updated"].format(date=date.isoformat()),
        "",
        s["intro"].format(contexts=context_label),
        "",
        s["h_short_memory"],
        "",
        s["short_intro"],
        "",
        *_render_short_term_memory(report, page_dir, s),
        "",
        s["h_contexts"],
        "",
        s["th_contexts"],
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if report.context_rows:
        for row in report.context_rows:
            hub = _page_link(row.hub, page_dir) if row.hub else s["none"]
            next_steps = _render_context_next_steps(row, report, page_dir, s)
            lines.append(
                f"| {_escape(row.context)} | {hub} | {s.get('vital_' + row.vitality, row.vitality)} | "
                f"{row.sources} | {row.source_attention} | {row.actions} | "
                f"{row.action_attention} | {row.claims} / {row.decisions} | {next_steps} |"
            )
    else:
        lines.append(s["empty_contexts"])

    lines += ["", s["h_outputs"], "", s["th_outputs"], "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    if report.consolidation_outputs:
        for row in report.consolidation_outputs:
            signal = s.get("signal_" + row.signal, row.signal)
            lines.append(
                f"| {_escape(row.context)} | {row.actions} | {row.problems} | {row.claims} | "
                f"{row.decisions} | {row.context_notes} | {row.non_ingested_sources} | {_escape(signal)} |"
            )
    else:
        lines.append(s["empty_outputs"])

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
                f"`{_escape(_action_display_state(action) or s['unknown'])}` | {_escape(action.updated_at or s['none'])} | "
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

    lines += ["", s["h_decision_blocks"], "", s["th_decision_blocks"], "| --- | --- | --- | --- | --- |"]
    if report.decision_action_blockers:
        for blocker in report.decision_action_blockers:
            action_link = _page_link(blocker.action, page_dir) if blocker.action else f"`{_escape(blocker.action_id)}`"
            action_context = blocker.action.context if blocker.action else blocker.decision.context
            action_status = (
                _action_display_state(blocker.action)
                if blocker.action
                else s["missing_action"]
            )
            lines.append(
                f"| {_page_link(blocker.decision, page_dir)} | {action_link} | {_escape(action_context)} | "
                f"`{_escape(blocker.decision.status or s['unknown'])}` | "
                f"`{_escape(action_status or s['unknown'])}` |"
            )
    else:
        lines.append(s["empty_decision_blocks"])

    lines += ["", s["h_attention"], "", s["th_attention"], "| --- | --- | --- | --- |"]
    if report.attention:
        for row in report.attention:
            lines.append(
                f"| {_escape(row.context)} | {_escape(row.page.page_type)} | "
                f"{_page_link(row.page, page_dir)} | {_escape(row.reason)} |"
            )
    else:
        lines.append(s["empty_attention"])

    lines.append("")
    lines += _render_operational_model(report.operational_model, page_dir, s)

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


def _render_short_term_memory(
    report: OperationalPassReport,
    page_dir: Path,
    s: dict[str, str],
) -> list[str]:
    lines: list[str] = []
    review_items = [
        f"- **{_escape(row.context)} / {_escape(row.page.page_type)}:** "
        f"{_page_link(row.page, page_dir)} — {_escape(row.reason)}"
        for row in _balanced_attention_rows(report, SHORT_TERM_LIMIT)
    ]
    lines.extend(_short_block(s["short_review_now"], review_items, s["short_no_review"]))

    actions_by_id = {action.page_id: action for action in report.actions}
    action_candidates: list[PageRecord] = []
    for action_id in report.pending_ids:
        action = actions_by_id.get(action_id)
        if action is not None and not _action_is_closed(action):
            action_candidates.append(action)
    for action in report.actions:
        if action in action_candidates:
            continue
        if _action_needs_attention(action):
            action_candidates.append(action)
    selected_actions = _balanced_page_rows(report, action_candidates, SHORT_TERM_LIMIT)
    action_items = [
        f"- **{_escape(action.context)}:** {_page_link(action, page_dir)} "
        f"({_escape(_action_display_state(action) or s['unknown'])})"
        for action in selected_actions
    ]
    lines.extend(_short_block(s["short_actions"], action_items, s["short_no_actions"]))

    decision_items = [
        f"- **{_escape(decision.context)}:** {_page_link(decision, page_dir)} "
        f"({_escape(decision.status or s['unknown'])})"
        for decision in report.pending_decisions[:SHORT_TERM_LIMIT]
    ]
    lines.extend(_short_block(s["short_decisions"], decision_items, s["short_no_decisions"]))

    recent_items = [
        f"- **{_escape(page.context)}:** {_page_link(page, page_dir)} "
        f"({_escape(page.updated_at or s['unknown'])})"
        for page in _recent_pages(report)[:SHORT_TERM_LIMIT]
    ]
    lines.extend(_short_block(s["short_recent"], recent_items, s["short_no_recent"]))
    return lines


def _balanced_attention_rows(
    report: OperationalPassReport, limit: int
) -> tuple[AttentionRow, ...]:
    """Pick short-memory attention rows across contexts before repeating one."""
    return _balanced_rows_by_context(
        report,
        list(report.attention),
        limit,
        context_of=lambda row: row.context,
    )


def _balanced_page_rows(
    report: OperationalPassReport, pages: list[PageRecord], limit: int
) -> tuple[PageRecord, ...]:
    """Pick short-memory pages across contexts before repeating one."""
    return _balanced_rows_by_context(
        report,
        pages,
        limit,
        context_of=lambda page: page.context,
    )


def _balanced_rows_by_context(
    report: OperationalPassReport,
    rows: list[Any],
    limit: int,
    *,
    context_of: Callable[[Any], str],
) -> tuple[Any, ...]:
    if limit <= 0:
        return ()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(context_of(row), []).append(row)
    if not grouped:
        return ()

    ordered_contexts: list[str] = []
    for context_row in report.context_rows:
        if context_row.context in grouped and context_row.context not in ordered_contexts:
            ordered_contexts.append(context_row.context)
    for row in rows:
        context = context_of(row)
        if context not in ordered_contexts:
            ordered_contexts.append(context)

    selected: list[Any] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for context in ordered_contexts:
            rows = grouped.get(context) or []
            if depth >= len(rows):
                continue
            selected.append(rows[depth])
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
        depth += 1
    return tuple(selected)


def _short_block(title: str, items: list[str], empty: str) -> list[str]:
    if not items:
        items = [f"- {empty}"]
    return [f"### {title}", "", *items, ""]


def _recent_pages(report: OperationalPassReport) -> list[PageRecord]:
    return list(report.recent_pages)


def _recent_pages_from_pages(pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    seen: dict[str, PageRecord] = {}
    for page in pages:
        seen.setdefault(page.rel, page)
    return sorted(
        seen.values(),
        key=lambda page: (
            _parse_date(page.updated_at) or dt.date.min,
            page.context,
            page.title.lower(),
            page.rel,
        ),
        reverse=True,
    )


def _render_operational_model(
    rows: tuple[OperationalModelRow, ...], page_dir: Path, s: dict[str, str]
) -> list[str]:
    lines: list[str] = [s["h_operational_model"], ""]
    has_content = any(row.roles for row in rows)
    if not has_content:
        lines.append(s["empty_operational_model"])
        return lines
    for row in rows:
        if not row.roles:
            continue
        lines.append(f"### {_escape(row.context)}")
        lines.append("")
        for role_node in row.roles:
            role_health = s.get("health_" + role_node.health, role_node.health)
            lines.append(
                f"- **{s['role_label']}:** {_page_link(role_node.page, page_dir)} "
                f"— {s['role_health_label']} `{role_health}`"
            )
            if role_node.assignment is not None:
                lines.append(
                    f"  - {s['assignment_label']}: {_page_link(role_node.assignment, page_dir)}"
                )
            for resp_node in role_node.responsibilities:
                resp_health = s.get("health_" + resp_node.health, resp_node.health)
                if resp_node.health == "sem_acao":
                    lines.append(
                        f"  - **{s['responsibility_label']}:** "
                        f"{_page_link(resp_node.page, page_dir)} — {s['responsibility_no_action']}"
                    )
                    continue
                lines.append(
                    f"  - **{s['responsibility_label']}:** "
                    f"{_page_link(resp_node.page, page_dir)} — {s['responsibility_health_label']} `{resp_health}`"
                )
                for action in resp_node.open_actions:
                    lines.append(
                        f"    - {s['action_label']}: {_page_link(action, page_dir)} "
                        f"`{_escape(_action_display_state(action) or s['unknown'])}`"
                    )
                    for step in parse_next_steps(action.body):
                        if step.done:
                            continue
                        suffix = (
                            f" — {s['trigger_label']}: {_escape(step.trigger)}"
                            if step.trigger
                            else ""
                        )
                        lines.append(
                            f"      - {s['next_step_label']}: {_escape(step.text)}{suffix}"
                        )
        lines.append("")
    lines.append(s["roleless_context"].format(count=sum(1 for r in rows if r.roleless_context)))
    return lines


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
        "consolidation_outputs": [
            {
                "context": r.context,
                "actions": r.actions,
                "problems": r.problems,
                "claims": r.claims,
                "decisions": r.decisions,
                "context_notes": r.context_notes,
                "non_ingested_sources": r.non_ingested_sources,
                "signal": r.signal,
            }
            for r in report.consolidation_outputs
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
                "action_state": a.action_state,
                "action_state_raw": a.action_state_raw,
                "action_state_source": a.action_state_source,
                "action_state_compatibility": a.action_state_compatibility,
                "action_state_warnings": list(a.action_state_warnings),
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
        "decision_action_blockers": [
            {
                "decision_page_id": b.decision.page_id,
                "decision_path": b.decision.rel,
                "decision_status": b.decision.status,
                "action_page_id": b.action.page_id if b.action else "",
                "action_path": b.action.rel if b.action else "",
                "action_id": b.action_id,
                "action_status": _action_display_state(b.action) if b.action else "",
            }
            for b in report.decision_action_blockers
        ],
        "attention": [
            {"context": a.context, "page_type": a.page.page_type, "path": a.page.rel, "reason": a.reason}
            for a in report.attention
        ],
        "operational_model": [
            {
                "context": row.context,
                "roleless_context": row.roleless_context,
                "roles": [
                    {
                        "page_id": role.page.page_id,
                        "path": role.page.rel,
                        "health": role.health,
                        "assignment": role.assignment.page_id if role.assignment else "",
                        "responsibilities": [
                            {
                                "page_id": resp.page.page_id,
                                "path": resp.page.rel,
                                "health": resp.health,
                                "open_actions": [
                                    {
                                        "page_id": a.page_id,
                                        "path": a.rel,
                                        "status": a.status,
                                        "action_state": a.action_state,
                                        "action_state_raw": a.action_state_raw,
                                        "action_state_source": a.action_state_source,
                                        "action_state_compatibility": (
                                            a.action_state_compatibility
                                        ),
                                        "action_state_warnings": list(
                                            a.action_state_warnings
                                        ),
                                    }
                                    for a in resp.open_actions
                                ],
                                "next_steps": [
                                    {"text": step.text, "trigger": step.trigger, "done": step.done}
                                    for step in resp.next_steps
                                ],
                            }
                            for resp in role.responsibilities
                        ],
                    }
                    for role in row.roles
                ],
            }
            for row in report.operational_model
        ],
        "pending_ids": list(report.pending_ids),
        "recent_pages": [
            {
                "page_id": page.page_id,
                "path": page.rel,
                "context": page.context,
                "page_type": page.page_type,
                "updated_at": page.updated_at,
            }
            for page in report.recent_pages[:SHORT_TERM_LIMIT]
        ],
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


def parse_next_steps(body: str) -> tuple[NextStep, ...]:
    """Extract ``- [ ]``/``- [x]`` items under a ``## Proximos passos`` section.

    Each item becomes a :class:`NextStep`; the trigger is the text after a
    ``gatilho:``/``trigger:`` marker. Parsing stops at the next heading so the
    extraction is local to the section and deterministic.
    """
    steps: list[NextStep] = []
    in_section = False
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        match = NEXT_STEP_ITEM_RE.match(current[0])
        if not match:
            current.clear()
            return
        done = match.group("mark").lower() == "x"
        rest = " ".join(
            [match.group("rest").strip(), *[line.strip() for line in current[1:] if line.strip()]]
        ).strip()
        trigger = ""
        trigger_match = NEXT_STEP_TRIGGER_RE.search(rest)
        if trigger_match:
            trigger = trigger_match.group("trigger").strip()
            rest = rest[: trigger_match.start()].strip()
        else:
            rest = NEXT_STEP_RESULT_RE.sub("", rest).strip()
        rest = rest.rstrip("—- ").strip()
        steps.append(NextStep(text=rest, trigger=trigger, done=done))
        current.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            flush()
            in_section = bool(NEXT_STEPS_HEADING_RE.match(line))
            continue
        if not in_section:
            continue
        match = NEXT_STEP_ITEM_RE.match(line)
        if match:
            flush()
            current.append(line)
            continue
        if current and line:
            current.append(line)
    flush()
    return tuple(steps)


def _action_is_closed(page: PageRecord) -> bool:
    return page.action_state in TERMINAL_ACTION_STATES


def _action_display_state(page: PageRecord) -> str:
    if page.action_state_source == "action_state":
        return page.action_state
    return page.action_state_raw or page.action_state


def _status_is_closed(status: str) -> bool:
    slug = _status_slug(status)
    return slug in CLOSED_STATUS_SLUGS or any(
        slug.startswith(prefix) for prefix in CLOSED_STATUS_PREFIXES
    )


def _status_slug(status: str) -> str:
    normalized = unicodedata.normalize("NFKD", status)
    ascii_status = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_status.lower()).strip("_")


def _action_needs_attention(page: PageRecord) -> bool:
    return not _action_is_closed(page) and _page_needs_attention(page)


def _build_responsibility_node(
    resp: PageRecord, actions_by_id: dict[str, PageRecord]
) -> ResponsibilityNode:
    actions = tuple(
        actions_by_id[aid]
        for aid in resp.actions
        if aid in actions_by_id
    )
    # Reciprocity: an action may point back at this responsibility even when the
    # responsibility frontmatter does not list it (incremental fill-in).
    for action in actions_by_id.values():
        action_resps = _string_tuple(action.frontmatter.get("responsibilities"))
        if resp.page_id in action_resps and action.page_id not in resp.actions:
            actions = actions + (action,)
    open_actions = tuple(
        sorted(
            (a for a in actions if not _action_is_closed(a)),
            key=lambda a: (a.title.lower(), a.rel),
        )
    )
    next_steps: list[NextStep] = []
    for action in open_actions:
        next_steps.extend(parse_next_steps(action.body))
    if not actions:
        health = "sem_acao"
    elif any(_page_needs_attention(a) for a in open_actions):
        health = "atencao"
    else:
        health = "ok"
    return ResponsibilityNode(
        page=resp,
        open_actions=open_actions,
        next_steps=tuple(next_steps),
        health=health,
    )


def _build_role_node(
    role: PageRecord,
    resp_by_id: dict[str, PageRecord],
    assign_by_role_id: dict[str, PageRecord],
    actions_by_id: dict[str, PageRecord],
) -> RoleNode:
    resp_ids: list[str] = list(_string_tuple(role.frontmatter.get("responsibilities")))
    # Reciprocity: responsibilities that list this role but are not yet listed
    # back in the role frontmatter still belong to the role.
    for resp in resp_by_id.values():
        roles = _string_tuple(resp.frontmatter.get("roles"))
        if role.page_id in roles and resp.page_id not in resp_ids:
            resp_ids.append(resp.page_id)
    nodes = tuple(
        sorted(
            (
                _build_responsibility_node(resp_by_id[rid], actions_by_id)
                for rid in dict.fromkeys(resp_ids)
                if rid in resp_by_id
            ),
            key=lambda node: (node.page.title.lower(), node.page.rel),
        )
    )
    health = "ok" if nodes else "sem_responsabilidade"
    return RoleNode(
        page=role,
        responsibilities=nodes,
        assignment=assign_by_role_id.get(role.page_id),
        health=health,
    )


def _operational_model_rows(
    pages: tuple[PageRecord, ...], contexts: tuple[str, ...]
) -> tuple[OperationalModelRow, ...]:
    resp_by_id = {p.page_id: p for p in pages if p.page_type == "responsibility"}
    role_by_id = {p.page_id: p for p in pages if p.page_type == "role"}
    actions_by_id = {p.page_id: p for p in pages if p.page_type == "action"}
    assign_by_role_id: dict[str, PageRecord] = {}
    for page in pages:
        if page.page_type != "assignment":
            continue
        for role_id in _string_tuple(page.frontmatter.get("roles")):
            assign_by_role_id.setdefault(role_id, page)

    rows: list[OperationalModelRow] = []
    for context in contexts:
        ctx_roles = tuple(
            sorted(
                (r for r in role_by_id.values() if r.context == context),
                key=lambda r: (r.title.lower(), r.rel),
            )
        )
        role_nodes = tuple(
            _build_role_node(role, resp_by_id, assign_by_role_id, actions_by_id)
            for role in ctx_roles
        )
        rows.append(
            OperationalModelRow(
                context=context,
                roles=role_nodes,
                roleless_context=not role_nodes,
            )
        )
    return tuple(rows)


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
    haystack = " ".join(
        (page.title, page.action_state, page.status, page.body[:2000])
    )
    return bool(ATTENTION_RE.search(haystack))


def _decision_needs_attention(page: PageRecord) -> bool:
    status = _status_slug(page.status)
    return (
        status not in NON_PENDING_DECISION_STATUS_SLUGS
        and not _status_is_closed(page.status)
        and _page_needs_attention(page)
    )


def _claim_needs_attention(page: PageRecord) -> bool:
    """Claims use epistemic status; facts should not become operational noise."""
    status = _status_slug(page.status)
    open_qualifier = _claim_has_open_attention_qualifier(page)
    if status in NON_ATTENTION_CLAIM_STATUS_SLUGS:
        return open_qualifier
    return open_qualifier or _page_needs_attention(page)


def _claim_has_open_attention_qualifier(page: PageRecord) -> bool:
    return bool(_claim_open_attention_reason(page))


def _claim_attention_reason(page: PageRecord) -> str:
    return _claim_open_attention_reason(page) or _attention_reason(page)


def _claim_open_attention_reason(page: PageRecord) -> str:
    haystack = " ".join((page.status, page.body[:2000]))
    bullet_match = OPEN_CLAIM_BULLET_RE.search(page.body[:2000])
    if bullet_match:
        return f"Open claim qualifier: `{_inline_excerpt(bullet_match.group('qualifier'))}`."
    for qualifier_match in OPEN_CLAIM_QUALIFIER_RE.finditer(haystack):
        if _is_negated_open_claim_match(haystack, qualifier_match.start()):
            continue
        return f"Open claim qualifier: `{_inline_excerpt(qualifier_match.group(1))}`."
    return ""


def _is_negated_open_claim_match(text: str, match_start: int) -> bool:
    prefix = text[max(0, match_start - 48) : match_start]
    normalized = unicodedata.normalize("NFKD", prefix)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return bool(NEGATED_OPEN_CLAIM_PREFIX_RE.search(normalized))


def _inline_excerpt(value: str, *, limit: int = 140) -> str:
    excerpt = " ".join(value.split()).strip()
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 3].rstrip() + "..."


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
    for page in actions:
        reason = _attention_reason(page) if _action_needs_attention(page) else ""
        if reason:
            rows.append(AttentionRow(page.context, page, reason))
    for page in claims:
        reason = _claim_attention_reason(page) if _claim_needs_attention(page) else ""
        if reason:
            rows.append(AttentionRow(page.context, page, reason))
    return rows


def _attention_reason(page: PageRecord) -> str:
    if _page_needs_attention(page):
        if page.page_type == "action" and page.action_state:
            return f"Action state: `{_action_display_state(page)}`."
        if page.status:
            return f"Status: `{page.status}`."
        return "Attention keyword detected; see linked page."
    return ""


def _decision_action_blockers(
    pending_decisions: tuple[PageRecord, ...],
    actions: tuple[PageRecord, ...],
) -> tuple[DecisionActionBlocker, ...]:
    by_id = {action.page_id: action for action in actions}
    blockers: list[DecisionActionBlocker] = []
    for decision in pending_decisions:
        for action_id in decision.actions:
            blockers.append(DecisionActionBlocker(decision, by_id.get(action_id), action_id))
    return tuple(blockers)


def _consolidation_outputs(
    context_names: tuple[str, ...],
    actions: tuple[PageRecord, ...],
    claims: tuple[PageRecord, ...],
    decisions: tuple[PageRecord, ...],
    context_notes: tuple[PageRecord, ...],
    sources: tuple[SourceRow, ...],
    attention: tuple[AttentionRow, ...],
    blockers: tuple[DecisionActionBlocker, ...],
) -> tuple[ConsolidationOutputRow, ...]:
    rows: list[ConsolidationOutputRow] = []
    for context in context_names:
        ctx_actions = [a for a in actions if a.context == context]
        ctx_claims = [c for c in claims if c.context == context]
        ctx_decisions = [d for d in decisions if d.context == context]
        ctx_notes = [n for n in context_notes if n.context == context]
        ctx_sources = [s for s in sources if s.page.context == context]
        ctx_attention = [a for a in attention if a.context == context]
        ctx_blockers = [
            b
            for b in blockers
            if (b.action.context if b.action else b.decision.context) == context
        ]
        non_ingested = sum(1 for source in ctx_sources if _source_is_non_ingested(source))
        rows.append(
            ConsolidationOutputRow(
                context=context,
                actions=len(ctx_actions),
                problems=len(ctx_attention),
                claims=len(ctx_claims),
                decisions=len(ctx_decisions),
                context_notes=len(ctx_notes),
                non_ingested_sources=non_ingested,
                signal=_output_signal(ctx_attention, ctx_blockers, non_ingested),
            )
        )
    return tuple(rows)


def _source_is_non_ingested(source: SourceRow) -> bool:
    state = source.ingestion_state.lower().replace("_", " ").replace("-", " ").strip()
    return state in {"not ingested", "nao ingerida", "nao ingerido", "não ingerida", "não ingerido", "skipped"}


def _output_signal(
    attention: list[AttentionRow],
    blockers: list[DecisionActionBlocker],
    non_ingested_sources: int,
) -> str:
    if blockers:
        return "blocked_by_decision"
    if non_ingested_sources:
        return "source_not_ingested"
    if attention:
        return "needs_review"
    return "ok"


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
        if action and action.context == context and not _action_is_closed(action):
            steps.append(
                f"{action.title} ({_action_display_state(action) or 'state unknown'})"
            )
        if len(steps) >= 3:
            return tuple(steps)
    for action in actions:
        if action.page_id not in pending_ids and _action_needs_attention(action):
            steps.append(
                f"{action.title} ({_action_display_state(action) or 'state unknown'})"
            )
        if len(steps) >= 3:
            return tuple(steps)
    for source in sources:
        if _source_needs_attention(source):
            steps.append(f"refresh source: {source.page.title} ({source.refresh_status})")
        if len(steps) >= 3:
            return tuple(steps)
    return tuple(steps)


def _render_context_next_steps(
    row: ContextRow,
    report: OperationalPassReport,
    page_dir: Path,
    s: dict[str, str],
) -> str:
    if not row.next_steps:
        return s["none"]
    rendered: list[str] = []
    context_actions = [action for action in report.actions if action.context == row.context]
    context_sources = [source for source in report.sources if source.page.context == row.context]
    for step in row.next_steps:
        linked = ""
        for action in context_actions:
            status = _action_display_state(action) or "state unknown"
            if step == f"{action.title} ({status})":
                linked = f"{_page_link(action, page_dir)} ({_escape(status)})"
                break
        if not linked:
            for source in context_sources:
                if step == f"refresh source: {source.page.title} ({source.refresh_status})":
                    linked = f"refresh source: {_page_link(source.page, page_dir)} ({_escape(source.refresh_status)})"
                    break
        rendered.append(linked or _escape(step))
    return "<br>".join(rendered)


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
    return "stale" if is_stale(updated, stale_after, as_of) else "fresh"


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
            "h_short_memory": "## Memoria de curto prazo",
            "short_intro": "Leia isto primeiro: estado compacto e diario dos itens que ainda precisam de revisao, decisao ou acao. As secoes completas continuam abaixo.",
            "short_review_now": "Revisar agora",
            "short_actions": "Acoes principais",
            "short_decisions": "Decisoes pendentes",
            "short_recent": "Ultimas atualizacoes",
            "short_no_review": "Nenhum item em atencao.",
            "short_no_actions": "Nenhuma acao pendente priorizada.",
            "short_no_decisions": "Nenhuma decisao pendente.",
            "short_no_recent": "Nenhuma atualizacao registrada.",
            "all_contexts": "todos",
            "h_contexts": "## Resumo por contexto",
            "th_contexts": "| Contexto | Hub | Vitalidade | Fontes | Fontes em atencao | Acoes | Acoes em atencao | Claims / decisoes | Proximos passos |",
            "h_outputs": "## Matriz de saidas de consolidacao",
            "th_outputs": "| Contexto | Acoes | Problemas | Claims | Decisoes | Contextos densos | Fontes nao ingeridas | Sinal |",
            "h_sources": "## Fontes por estado",
            "th_sources": "| Fonte | Contexto | Ingestao | Ultima atualizacao | Proxima revisao | Status | Acoes ligadas |",
            "h_actions": "## Acoes compiladas",
            "th_actions": "| Acao | Contexto | Estado | Atualizacao | Fontes | Sinal |",
            "h_decisions": "## Decisoes pendentes",
            "th_decisions": "| Decisao | Contexto | Estado | Atualizacao | Acoes ligadas | Sinal |",
            "h_decision_blocks": "## Acoes bloqueadas por decisao pendente",
            "th_decision_blocks": "| Decisao | Acao | Contexto da acao | Estado da decisao | Estado da acao |",
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
            "missing_action": "acao sem pagina",
            "signal_blocked_by_decision": "bloqueado por decisao",
            "signal_source_not_ingested": "fonte nao ingerida",
            "signal_needs_review": "revisar",
            "signal_ok": "ok",
            "vital_fresh": "fresca",
            "vital_stale": "stale",
            "vital_missing": "sem hub",
            "vital_unknown": "indeterminada",
            "empty_contexts": "| Sem contextos encontrados. | - | - | - | - | - | - | - | - |",
            "empty_outputs": "| Sem saidas de consolidacao. | - | - | - | - | - | - | - |",
            "empty_sources": "| Sem fontes registradas. | - | - | - | - | - | - |",
            "empty_actions": "| Sem acoes registradas. | - | - | - | - | - |",
            "empty_decisions": "| Sem decisoes pendentes detectadas. | - | - | - | - | - |",
            "empty_decision_blocks": "| Nenhuma acao bloqueada por decisao pendente. | - | - | - | - |",
            "empty_attention": "| Sem problemas ou incertezas detectados por heuristica. | - | - | - |",
            "h_operational_model": "## Modelo operacional por contexto",
            "role_label": "Papel",
            "role_health_label": "saudavel?",
            "responsibility_label": "Responsabilidade",
            "responsibility_health_label": "em dia?",
            "action_label": "Acao",
            "next_step_label": "Proximo passo",
            "trigger_label": "gatilho",
            "assignment_label": "Atribuicao",
            "responsibility_no_action": "sem acao aberta (preventiva)",
            "roleless_context": "_(contextos sem papel preenchido: {count})_",
            "empty_operational_model": "_(sem papeis preenchidos por contexto.)_",
            "health_ok": "ok",
            "health_atencao": "atencao",
            "health_sem_acao": "sem acao",
            "health_sem_responsabilidade": "sem responsabilidade",
        },
        "en": {
            "title": "Operational pass - sources, actions and contexts",
            "purpose": "cross-context compilation of sources, actions, uncertainty and next steps",
            "updated": "Updated at: {date}.",
            "intro": "Deterministic compilation for contexts: {contexts}. Use this page to compress next steps into actions, problems, claims, decisions and target pages; it does not replace human reading of live sources.",
            "h_short_memory": "## Short-term memory",
            "short_intro": "Read this first: a compact daily state of items that still need review, decision or action. Full diagnostic sections remain below.",
            "short_review_now": "Review now",
            "short_actions": "Primary actions",
            "short_decisions": "Pending decisions",
            "short_recent": "Latest updates",
            "short_no_review": "No attention items.",
            "short_no_actions": "No prioritized pending actions.",
            "short_no_decisions": "No pending decisions.",
            "short_no_recent": "No recorded updates.",
            "all_contexts": "all",
            "h_contexts": "## Context summary",
            "th_contexts": "| Context | Hub | Vitality | Sources | Sources needing attention | Actions | Actions needing attention | Claims / decisions | Next steps |",
            "h_outputs": "## Consolidation output matrix",
            "th_outputs": "| Context | Actions | Problems | Claims | Decisions | Dense contexts | Non-ingested sources | Signal |",
            "h_sources": "## Sources by state",
            "th_sources": "| Source | Context | Ingestion | Last update | Next refresh | Status | Linked actions |",
            "h_actions": "## Compiled actions",
            "th_actions": "| Action | Context | State | Updated | Sources | Signal |",
            "h_decisions": "## Pending decisions",
            "th_decisions": "| Decision | Context | State | Updated | Linked actions | Signal |",
            "h_decision_blocks": "## Actions gated by pending decisions",
            "th_decision_blocks": "| Decision | Action | Action context | Decision state | Action state |",
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
            "missing_action": "missing action page",
            "signal_blocked_by_decision": "blocked by decision",
            "signal_source_not_ingested": "source not ingested",
            "signal_needs_review": "needs review",
            "signal_ok": "ok",
            "vital_fresh": "fresh",
            "vital_stale": "stale",
            "vital_missing": "missing hub",
            "vital_unknown": "unknown",
            "empty_contexts": "| No contexts found. | - | - | - | - | - | - | - | - |",
            "empty_outputs": "| No consolidation outputs. | - | - | - | - | - | - | - |",
            "empty_sources": "| No sources recorded. | - | - | - | - | - | - |",
            "empty_actions": "| No actions recorded. | - | - | - | - | - |",
            "empty_decisions": "| No pending decisions detected. | - | - | - | - | - |",
            "empty_decision_blocks": "| No action gated by a pending decision. | - | - | - | - |",
            "empty_attention": "| No heuristic problems or uncertainty detected. | - | - | - |",
            "h_operational_model": "## Operational model by context",
            "role_label": "Role",
            "role_health_label": "healthy?",
            "responsibility_label": "Responsibility",
            "responsibility_health_label": "on track?",
            "action_label": "Action",
            "next_step_label": "Next step",
            "trigger_label": "trigger",
            "assignment_label": "Assignment",
            "responsibility_no_action": "no open action (preventive)",
            "roleless_context": "_(contexts without a filled role: {count})_",
            "empty_operational_model": "_(no roles filled per context.)_",
            "health_ok": "ok",
            "health_atencao": "attention",
            "health_sem_acao": "no action",
            "health_sem_responsabilidade": "no responsibility",
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
    return parse_updated_date(_date_text(value))


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
