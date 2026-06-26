#!/usr/bin/env python3
"""Compile the daily operation cockpit from the living wiki and Git state.

The cockpit page (config key `paths.operation_page`, default
`memories/operations.md`) is generated from real sources, never from hardcoded
personal content:

- repo_id / owner_label come from `wiki.config.yaml` (via `load_config`);
- decisions come from `<memory_root>/<decisions_dirname>/*.md` (one per file);
- actions come from `<memory_root>/<actions_dirname>/*.md` plus the pending
  queue file (`<actions_dirname>/<pending_actions_filename>`);
- context vitality is derived from `updated_at` + `stale_after_days` of the
  context hubs (`<memory_root>/*/index.md`);
- Git state is intentionally not persisted in the versioned cockpit because it
  goes stale as soon as a proposal branch is merged; check it live before acting.

`build_page(root, config)` takes an injectable `root`, so it can be exercised
against a minimal repo in tests without touching the real working tree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.closure import build_ingestion_closure_report
from wiki_core.consolidate import pending_consolidations
from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.score import compute_karma, load_events, record_event, resolve_events_path

# Context hubs are the pages that carry living context per area. Their
# freshness drives the "Context vitality" table.
CONTEXT_HUB_TYPE = "context_hub"

H1_RE = re.compile(r"^#\s+(.*\S)\s*$")
# Bilingual: action pages may carry "Estado:" (pt) or "State:" (en) lines.
STATE_PREFIX_RE = re.compile(r"^(?:Estado|State):\s*(.+?)\s*$")
# Bilingual: H1 titles may carry "Decisao - " / "Decision - " / "Acao - " /
# "Action - " prefixes; the cockpit tables list the bare title.
TITLE_PREFIX_RE = re.compile(r"^(?:Decisao|Decision|Acao|Action)\s*-\s*")
LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+?)\s*$")
ACTION_ID_RE = re.compile(r"`([^`]+)`|\b((?:acao|action)-[A-Za-z0-9_.:-]+)\b")

# Deterministic sections derived from the memory-tree content (independent of
# date/git state): fine granularity, still used by per-section drift tests.
# Their header prefixes come from the ACTIVE language's string table (see
# checked_section_prefixes) — a fixed pt tuple silently matched nothing on en.
CHECKED_SECTION_KEYS = ("h_decisions", "h_actions", "h_queue")

# VOLATILE parts of the cockpit (depend on date, git state or karma/score). They
# stay out of the stable view used by --check. Includes the markers in both pt AND en
# so that --check works regardless of `language` in the config.
VOLATILE_FRONTMATTER_KEYS = ("updated_at", "generated_from_commit", "generated_from_branch")
VOLATILE_SECTIONS = (
    "Vitalidade dos contextos", "Context vitality",
    "Karma e vitalidade", "Karma and vitality",
)
VOLATILE_BODY_PREFIXES = (
    "Atualizado em:", "Updated at:",
    "- Compilado de:", "- Compiled from:",
    "- Estado no momento da compilacao", "- Compile-time state",
    "- Branch de proposta", "- Proposal branch",
    "- Estado aprovado", "- Approved state",
    "- Branch `",
    "- Contextos stale para revisar:", "- Stale contexts to review:",
    # Depends on the gitignored derived cache (llm-cache/extraction-events):
    # present locally, absent on a clean clone — volatile by construction.
    "- Fontes aguardando consolidacao:", "- Sources awaiting consolidation:",
)

# Cockpit string table per language (drives the GENERATED output via config.language).
# Keys with {placeholders} are formatted in build_page.
COCKPIT_STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "purpose": "cockpit de retomada operacional diaria da wiki",
        "title": "Operacao - {repo}",
        "owner": "Dono: {owner}.",
        "updated": "Atualizado em: {now}.",
        "h_state": "## Estado agora",
        "git_state_hint": "- Estado Git atual: verifique ao vivo com `git status --short --branch` e o PR antes de agir; commit e branch nao sao versionados no cockpit porque ficam obsoletos apos merge.",
        "generated_by": "- Gerado por [scripts/wiki_operation_compile.py](../scripts/wiki_operation_compile.py); o conteudo deterministico do cockpit e verificado no CI via `--check`.",
        "biggest_risk": "- Maior risco: consolidar memoria canonica sem PR ou sem fonte linkada.",
        "h_decisions": "## Decisoes pendentes",
        "th_decisions": "| Decisao | Contexto | Fonte |",
        "empty_decisions": "| Sem decisoes pendentes registradas. | - | - |",
        "h_actions": "## Acoes do dono ({owner})",
        "th_actions": "| Acao | Contexto | Estado | Fonte |",
        "empty_actions": "| Sem acoes registradas. | - | - | - |",
        "h_queue": "## Fila de acoes pendentes",
        "queue_listed": "Identificadores listados em [{pending_path}]({pending_path}):",
        "empty_queue": "Sem acoes pendentes registradas.",
        "consolidation_pending": "- Fontes aguardando consolidacao: {count} — ver [scripts/wiki_consolidate.py]({script}).",
        "h_alerts": "## Alertas",
        "alert_stale": "- A pagina de operacao fica stale apos 1 dia.",
        "alert_quadrants": "- Eventos de ingestao relevantes devem declarar quatro quadrantes ou ausencia explicita.",
        "alert_pii": "- Dados pessoais (PII: nomes, valores, CPF/CNPJ, contrapartes) sao bem-vindos na wiki privada; redigir so antes de exportar/publicar.",
        "alert_secrets": "- Segredos de acesso (tokens, senhas, chaves, cookies) nunca entram em lugar nenhum.",
        "alert_stale_contexts": "- Contextos stale para revisar: {contexts}.",
        "h_closure": "## Fechamento da ingestao",
        "closure_intro": "Sinal honesto: fonte ingerida so vale quando o evento e fechado (consolidado na memoria canonica). 0 fonte sem evento fechado = saudavel.",
        "th_closure": "| Metrica | Valor |",
        "closure_events_closed": "| Eventos de ingestao fechados | {closed}/{total} |",
        "closure_sources_closed": "| Fontes ingeridas com evento fechado | {closed}/{total} |",
        "closure_sources_gap": "| Fontes ingeridas SEM evento fechado (0 = saudavel) | {gap} |",
        "closure_compression": "| Compressao candidatos -> alvos | {candidates} -> {targets} ({ratio} por alvo) |",
        "closure_report_link": "- Relatorio detalhado: [scripts/wiki_ingestion_closure_report.py]({script}).",
        "closure_empty": "Sem eventos de ingestao registrados ainda.",
        "h_vitality": "## Vitalidade dos contextos",
        "th_vitality": "| Contexto | Atualizacao | Janela (dias) | Vitalidade | Hub |",
        "empty_vitality": "| Sem hubs de contexto registrados. | - | - | - | - |",
        "h_karma": "## Karma e vitalidade (gamificacao)",
        "karma_summary": "Eventos de score: {n} | karma total (com decaimento): {total}.",
        "th_karma": "| Dimensao | Pontos |",
        "empty_karma": "Sem eventos de score registrados (score-events.jsonl vazio/ausente).",
        "h_links": "## Links de retomada",
        "link_wiki": "Wiki", "link_log": "Log",
        "link_coverage": "Cobertura", "link_coverage_meth": "Cobertura metodologia",
        "link_operational_pass": "Passagem operacional",
        "vit_fresh": "fresca", "vit_stale": "stale", "vit_undetermined": "indeterminada",
        "no_state": "sem estado",
        "no_date": "sem data",
    },
    "en": {
        "purpose": "daily operational resume cockpit of the wiki",
        "title": "Operations - {repo}",
        "owner": "Owner: {owner}.",
        "updated": "Updated at: {now}.",
        "h_state": "## Current state",
        "git_state_hint": "- Current Git state: check live with `git status --short --branch` and the PR before acting; commit and branch are not versioned in the cockpit because they go stale after merge.",
        "generated_by": "- Generated by [scripts/wiki_operation_compile.py](../scripts/wiki_operation_compile.py); the cockpit's deterministic content is verified in CI via `--check`.",
        "biggest_risk": "- Biggest risk: consolidating canonical memory without a PR or a linked source.",
        "h_decisions": "## Pending decisions",
        "th_decisions": "| Decision | Context | Source |",
        "empty_decisions": "| No pending decisions recorded. | - | - |",
        "h_actions": "## Owner actions ({owner})",
        "th_actions": "| Action | Context | State | Source |",
        "empty_actions": "| No actions recorded. | - | - | - |",
        "h_queue": "## Pending action queue",
        "queue_listed": "Identifiers listed in [{pending_path}]({pending_path}):",
        "empty_queue": "No pending actions recorded.",
        "consolidation_pending": "- Sources awaiting consolidation: {count} — see [scripts/wiki_consolidate.py]({script}).",
        "h_alerts": "## Alerts",
        "alert_stale": "- The operations page goes stale after 1 day.",
        "alert_quadrants": "- Relevant ingestion events must declare the four quadrants or explicit absence.",
        "alert_pii": "- Personal data (PII: names, amounts, tax IDs, counterparties) is welcome in the private wiki; redact only before exporting/publishing.",
        "alert_secrets": "- Access secrets (tokens, passwords, keys, cookies) never go anywhere.",
        "alert_stale_contexts": "- Stale contexts to review: {contexts}.",
        "h_closure": "## Ingestion closure",
        "closure_intro": "Honest signal: an ingested source only counts once its event is closed (consolidated into canonical memory). 0 sources without a closed event = healthy.",
        "th_closure": "| Metric | Value |",
        "closure_events_closed": "| Closed ingestion events | {closed}/{total} |",
        "closure_sources_closed": "| Ingested sources with a closed event | {closed}/{total} |",
        "closure_sources_gap": "| Ingested sources WITHOUT a closed event (0 = healthy) | {gap} |",
        "closure_compression": "| Candidate -> target compression | {candidates} -> {targets} ({ratio} per target) |",
        "closure_report_link": "- Detailed report: [scripts/wiki_ingestion_closure_report.py]({script}).",
        "closure_empty": "No ingestion events recorded yet.",
        "h_vitality": "## Context vitality",
        "th_vitality": "| Context | Updated | Window (days) | Vitality | Hub |",
        "empty_vitality": "| No context hubs recorded. | - | - | - | - |",
        "h_karma": "## Karma and vitality (gamification)",
        "karma_summary": "Score events: {n} | total karma (with decay): {total}.",
        "th_karma": "| Dimension | Points |",
        "empty_karma": "No score events recorded (score-events.jsonl empty/absent).",
        "h_links": "## Resume links",
        "link_wiki": "Wiki", "link_log": "Log",
        "link_coverage": "Coverage", "link_coverage_meth": "Methodology coverage",
        "link_operational_pass": "Operational pass",
        "vit_fresh": "fresh", "vit_stale": "stale", "vit_undetermined": "undetermined",
        "no_state": "no state",
        "no_date": "no date",
    },
}


def _cs(language: str) -> dict[str, str]:
    """Cockpit string table for the language (fallback en)."""
    return COCKPIT_STRINGS.get(language, COCKPIT_STRINGS["en"])


def stable_cockpit_view(page: str) -> str:
    """Deterministic view of the cockpit for --check.

    Keeps everything that comes from the CONTENT of the memory tree and removes
    whatever depends on date, git state or karma/score. Covers the whole body (stable
    frontmatter, Current state, Decisions, Actions, Queue, Alerts, Links), not just
    3 sections. Commit hash equality is NOT required (by design: the recompile commit
    cannot contain its own hash, and merge commits always differ); the gate is the content.
    """
    out: list[str] = []
    in_fm = False
    fm_closed = False
    in_volatile_section = False
    for line in page.splitlines():
        if not fm_closed and line.strip() == "---":
            in_fm = not in_fm
            if not in_fm:
                fm_closed = True
            out.append(line)
            continue
        if in_fm:
            key = line.split(":", 1)[0].strip() if ":" in line else ""
            if key in VOLATILE_FRONTMATTER_KEYS:
                continue
            out.append(line)
            continue
        if line.startswith("## "):
            header = line[3:].strip()
            in_volatile_section = header.startswith(VOLATILE_SECTIONS)
            if in_volatile_section:
                continue
            out.append(line)
            continue
        if in_volatile_section:
            continue
        if line.startswith(VOLATILE_BODY_PREFIXES):
            continue
        out.append(line)
    return "\n".join(out).strip()


def page_sections(page: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in page.splitlines():
        if line.startswith("## "):
            if current is not None:
                blocks[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        blocks[current] = "\n".join(buf).strip()
    return blocks


def checked_section_prefixes(language: str) -> tuple[str, ...]:
    """Header prefixes of the deterministic sections in the active language.

    Derived from the string table ("## Header" / "## Header ({owner})" shapes),
    so the per-section drift check works for every supported language.
    """
    s = _cs(language)
    prefixes: list[str] = []
    for key in CHECKED_SECTION_KEYS:
        header = s[key]
        if header.startswith("## "):
            header = header[3:]
        prefixes.append(header.split("{", 1)[0].rstrip(" ("))
    return tuple(prefixes)


def checked_sections(page: str, language: str) -> dict[str, str]:
    prefixes = checked_section_prefixes(language)
    return {
        header: body
        for header, body in page_sections(page).items()
        if header.startswith(prefixes)
    }


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal scalar frontmatter parser (block-list values are ignored)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for raw in lines[1:]:
        stripped = raw.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def first_h1(text: str) -> str:
    for line in text.splitlines():
        match = H1_RE.match(line)
        if match:
            return match.group(1)
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


def _clean_title(title: str) -> str:
    """Strip a leading "Decisao - "/"Decision - "/"Acao - "/"Action - " prefix
    and any markdown links."""
    title = TITLE_PREFIX_RE.sub("", title)
    title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
    return title.strip()


@dataclass(frozen=True)
class Decision:
    page_id: str
    title: str
    context: str
    rel_link: str


@dataclass(frozen=True)
class Action:
    page_id: str
    title: str
    context: str
    state: str
    rel_link: str


def _rel_to_page_dir(path: Path, page_dir: Path) -> str:
    """Link target relative to the cockpit page's directory (POSIX)."""
    return Path(os.path.relpath(path, page_dir)).as_posix()


# Sibling pages that live next to decision/action items but are not items
# themselves. Superset (pt + en) for compatibility with localized repos.
NON_ITEM_BASENAMES = frozenset({"index.md", "concluidas.md", "completed.md"})
NON_PENDING_DECISION_STATUS_SLUGS = frozenset(
    {
        "active",
        "ativa",
        "ativo",
        "closed",
        "complete",
        "completed",
        "concluida",
        "concluido",
        "concluded",
        "decided",
        "decidida",
        "decidido",
        "done",
        "resolved",
        "resolvida",
        "resolvido",
    }
)
NON_PENDING_DECISION_STATUS_PREFIXES = (
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
    "decided_at_",
    "decided_em_",
    "decidida_at_",
    "decidida_em_",
    "decidido_at_",
    "decidido_em_",
    "done_at_",
    "done_em_",
    "resolved_at_",
    "resolved_em_",
    "resolvida_at_",
    "resolvida_em_",
    "resolvido_at_",
    "resolvido_em_",
)


def _status_slug(status: str) -> str:
    normalized = unicodedata.normalize("NFKD", status)
    ascii_status = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_status.lower()).strip("_")


def _decision_is_pending(values: dict[str, str], text: str) -> bool:
    status = str(values.get("status") or first_state(text) or "").strip()
    if not status:
        return False
    slug = _status_slug(status)
    return slug not in NON_PENDING_DECISION_STATUS_SLUGS and not any(
        slug.startswith(prefix) for prefix in NON_PENDING_DECISION_STATUS_PREFIXES
    )


def collect_decisions(paths: WikiPaths) -> list[Decision]:
    decisions_dir = paths.decisions_dir
    if not decisions_dir.is_dir():
        return []
    page_dir = paths.operation_page.parent
    decisions: list[Decision] = []
    for path in sorted(decisions_dir.glob("*.md")):
        if path.name in NON_ITEM_BASENAMES:
            continue
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        page_type = fm.get("page_type")
        # Accept decision pages (and untyped files); skip indexes/other types.
        if page_type is not None and page_type != "decision":
            continue
        if not _decision_is_pending(fm, text):
            continue
        title = _clean_title(first_h1(text)) or path.stem
        decisions.append(
            Decision(
                page_id=fm.get("page_id", path.stem),
                title=title,
                context=fm.get("context", paths.config.default_context),
                rel_link=_rel_to_page_dir(path, page_dir),
            )
        )
    return decisions


def collect_actions(paths: WikiPaths) -> list[Action]:
    actions_dir = paths.actions_dir
    if not actions_dir.is_dir():
        return []
    page_dir = paths.operation_page.parent
    # The pending-queue file is configurable; skip the known default names too
    # (pt + en superset) for compatibility with localized repos.
    skip = NON_ITEM_BASENAMES | {
        paths.pending_actions_file.name,
        "pendentes.md",
        "pending.md",
    }
    actions: list[Action] = []
    for path in sorted(actions_dir.glob("*.md")):
        if path.name in skip:
            continue
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm.get("page_type") != "action":
            continue
        title = _clean_title(first_h1(text)) or path.stem
        actions.append(
            Action(
                page_id=fm.get("page_id", path.stem),
                title=title,
                context=fm.get("context", paths.config.default_context),
                # Empty when the page has no Estado/State line; build_page renders
                # the language-table fallback (COCKPIT_STRINGS["no_state"]).
                state=first_state(text),
                rel_link=_rel_to_page_dir(path, page_dir),
            )
        )
    return actions


def pending_action_ids(paths: WikiPaths) -> list[str]:
    pending_file = paths.pending_actions_file
    if not pending_file.exists():
        return []
    ids: list[str] = []
    body_started = False
    for line in pending_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            body_started = True
            continue
        if not body_started:
            continue
        match = LIST_ITEM_RE.match(line)
        if not match:
            continue
        id_match = ACTION_ID_RE.search(match.group(1))
        if id_match:
            ids.append((id_match.group(1) or id_match.group(2)).strip())
    return ids


@dataclass(frozen=True)
class ContextVitality:
    context: str
    rel_link: str
    updated_at: str
    stale_after_days: int | None
    vitality: str


def _vitality_for(updated_at: str, stale_after_days: str, today: dt.date) -> tuple[str, int | None]:
    """Returns a canonical vitality KEY (stale/fresh/undetermined) + window. The
    translation for display happens in build_page via the language table."""
    try:
        updated = dt.date.fromisoformat(updated_at)
        stale_after = int(stale_after_days)
    except (ValueError, TypeError):
        return "undetermined", None
    deadline = updated + dt.timedelta(days=stale_after)
    if deadline < today:
        return "stale", stale_after
    return "fresh", stale_after


def collect_context_vitality(paths: WikiPaths, today: dt.date) -> list[ContextVitality]:
    rows: list[ContextVitality] = []
    if not paths.memory_root.is_dir():
        return rows
    page_dir = paths.operation_page.parent
    for index_path in sorted(paths.memory_root.glob("*/index.md")):
        fm = parse_frontmatter(index_path.read_text(encoding="utf-8"))
        if fm.get("page_type") != CONTEXT_HUB_TYPE:
            continue
        updated_at = fm.get("updated_at", "")
        vitality, stale_after = _vitality_for(updated_at, fm.get("stale_after_days", ""), today)
        rows.append(
            ContextVitality(
                context=fm.get("context", index_path.parent.name),
                rel_link=_rel_to_page_dir(index_path, page_dir),
                updated_at=updated_at,
                stale_after_days=stale_after,
                vitality=vitality,
            )
        )
    return rows


def _closure_section_lines(
    root: Path, config: WikiConfig, s: dict[str, str], page_dir: Path
) -> list[str]:
    """Deterministic "ingestion closure" section (Phase 4.1 primary metric).

    Built from `build_ingestion_closure_report`, whose inputs are versioned page
    frontmatter only — so the output is reproducible from committed content and
    safe to keep in the --check stable view. On any read error we degrade to an
    empty-but-honest placeholder rather than crashing the cockpit.
    """
    lines = ["", s["h_closure"], ""]
    try:
        summary = build_ingestion_closure_report(root, config)["summary"]
    except Exception:
        summary = None
    if not summary or int(summary["events_total"]) == 0:
        lines.append(s["closure_empty"])
        return lines
    report_link = _rel_to_page_dir(
        root / "scripts" / "wiki_ingestion_closure_report.py", page_dir
    )
    lines.append(s["closure_intro"])
    lines += ["", s["th_closure"], "| --- | ---: |"]
    lines.append(
        s["closure_events_closed"].format(
            closed=int(summary["events_closed"]), total=int(summary["events_total"])
        )
    )
    lines.append(
        s["closure_sources_closed"].format(
            closed=int(summary["ingested_sources"])
            - int(summary["ingested_sources_without_closed_event"]),
            total=int(summary["ingested_sources"]),
        )
    )
    lines.append(
        s["closure_sources_gap"].format(
            gap=int(summary["ingested_sources_without_closed_event"])
        )
    )
    lines.append(
        s["closure_compression"].format(
            candidates=int(summary["candidate_total"]),
            targets=int(summary["consolidated_targets"]),
            ratio=summary["candidate_units_per_target"],
        )
    )
    lines.append("")
    lines.append(s["closure_report_link"].format(script=report_link))
    return lines


def build_page(root: Path, config: WikiConfig) -> str:
    """Compile the cockpit Markdown for ``root`` using ``config``.

    ``root`` is injectable so this can run against a minimal repo in tests.
    """
    paths = WikiPaths(root, config)
    now = dt.datetime.now().replace(microsecond=0)
    today = dt.date.today()
    owner_label = config.owner_label
    repo_id = config.repo_id

    s = _cs(config.language)
    decisions = collect_decisions(paths)
    actions = collect_actions(paths)
    pending_ids = pending_action_ids(paths)
    vitality = collect_context_vitality(paths, today)

    # The page id is derived from the configured cockpit filename, so localized
    # repos keep generating their localized ids (e.g. operacao-* vs operations-*).
    page_id_prefix = Path(config.paths["operation_page"]).stem
    lines: list[str] = [
        "---",
        f"page_id: {page_id_prefix}-{config.repo_id}",
        "page_type: dashboard",
        f"context: {config.default_context}",
        f"visibility: {config.default_visibility}",
        f"updated_at: {today.isoformat()}",
        "stale_after_days: 1",
        "sources_policy: memorias_logs_git_e_artefatos_derivados",
        f"gate: {config.approval.get('gate', 'github_pr')}",
        "sensitive_data_policy: private_sensitive_allowed",
        f"purpose: {s['purpose']}",
        f"moc_parent: {config.paths['memory_root']}/index.md",
        "---",
        "",
        f"# {s['title'].format(repo=repo_id)}",
        "",
        s["owner"].format(owner=owner_label),
        s["updated"].format(now=now.isoformat(sep=' ', timespec='minutes')),
        "",
        s["h_state"],
        "",
        s["git_state_hint"],
        s["generated_by"],
        s["biggest_risk"],
        "",
        s["h_decisions"],
        "",
        s["th_decisions"],
        "| --- | --- | --- |",
    ]

    if decisions:
        for decision in decisions:
            lines.append(
                f"| [{decision.title}]({decision.rel_link}) | {decision.context} | "
                f"`{decision.page_id}` |"
            )
    else:
        lines.append(s["empty_decisions"])

    lines += [
        "",
        s["h_actions"].format(owner=owner_label),
        "",
        s["th_actions"],
        "| --- | --- | --- | --- |",
    ]

    if actions:
        for action in actions:
            state = action.state or s["no_state"]
            lines.append(
                f"| [{action.title}]({action.rel_link}) | {action.context} | {state} | "
                f"[{action.page_id}]({action.rel_link}) |"
            )
    else:
        lines.append(s["empty_actions"])

    lines += [
        "",
        s["h_queue"],
        "",
    ]
    if pending_ids:
        pending_rel = _rel_to_page_dir(paths.pending_actions_file, paths.operation_page.parent)
        lines.append(s["queue_listed"].format(pending_path=pending_rel))
        lines.append("")
        for action_id in pending_ids:
            lines.append(f"- `{action_id}`")
    else:
        lines.append(s["empty_queue"])

    lines += [
        "",
        s["h_alerts"],
        "",
        s["alert_stale"],
        s["alert_quadrants"],
        s["alert_pii"],
        s["alert_secrets"],
    ]
    stale_contexts = [row for row in vitality if row.vitality == "stale"]
    if stale_contexts:
        rendered = ", ".join(sorted(row.context for row in stale_contexts))
        lines.append(s["alert_stale_contexts"].format(contexts=rendered))
    # Consolidation backlog (volatile: derived cache is local-only). Keeps the
    # "ingesting = integrating" loop visible on every daily resume.
    try:
        consolidation_count = len(pending_consolidations(root, config))
    except Exception:
        consolidation_count = 0
    consolidate_script = _rel_to_page_dir(root / "scripts" / "wiki_consolidate.py", paths.operation_page.parent)
    lines.append(s["consolidation_pending"].format(count=consolidation_count, script=consolidate_script))

    # PRIMARY HONEST METRIC (Phase 4.1): ingestion closure. The karma score left
    # the cockpit; closure takes its place. This is DETERMINISTIC — derived from
    # VERSIONED page frontmatter (source pages + ingestion-event pages), not from
    # the gitignored derived cache — so it stays IN the --check stable view: a
    # divergence between committed cockpit and recompile is a real signal, not
    # churn. "0 sources without a closed event" is the healthy target.
    lines += _closure_section_lines(root, config, s, paths.operation_page.parent)

    lines += [
        "",
        s["h_vitality"],
        "",
        s["th_vitality"],
        "| --- | --- | --- | --- | --- |",
    ]
    if vitality:
        for row in vitality:
            window = "-" if row.stale_after_days is None else str(row.stale_after_days)
            updated = row.updated_at or s["no_date"]
            vit = s.get(f"vit_{row.vitality}", row.vitality)
            lines.append(
                f"| {row.context} | {updated} | {window} | {vit} | "
                f"[{row.rel_link}]({row.rel_link}) |"
            )
    else:
        lines.append(s["empty_vitality"])

    # Operational karma (gamification, opt-in via config.karma.enabled). When the
    # repo disables karma, the cockpit omits the whole score section. The karma
    # heading is already a VOLATILE_SECTION, so the --check stable view is
    # unaffected either way.
    if config.karma_enabled:
        # Read the live ledger (gitignored) or the versioned mirror (clean clone/CI).
        events = load_events(resolve_events_path(paths.derived_root))
        karma = compute_karma(events)
        lines += [
            "",
            s["h_karma"],
            "",
        ]
        if events:
            lines.append(s["karma_summary"].format(n=len(events), total=round(float(karma["total"]), 2)))
            lines += ["", s["th_karma"], "| --- | --- |"]
            for dim, points in sorted(karma["by_dimension"].items(), key=lambda kv: kv[1], reverse=True):
                if points:
                    lines.append(f"| {dim} | {round(float(points), 2)} |")
        else:
            lines.append(s["empty_karma"])

    # Resume links: labels are the repo-relative paths, targets are relative to
    # the cockpit page's directory — both derived from the configured layout.
    page_dir = paths.operation_page.parent
    resume_targets = (
        ("link_wiki", paths.memory_root / "index.md"),
        ("link_log", paths.log_page),
        ("link_operational_pass", paths.operational_pass_page),
        ("link_coverage", root / config.paths["wiki_coverage_page"]),
        ("link_coverage_meth", root / str(config.coverage["coverage_matrix_page"])),
    )
    lines += ["", s["h_links"], ""]
    for label_key, target_path in resume_targets:
        lines.append(
            f"- {s[label_key]}: "
            f"[{paths.rel(target_path)}]({_rel_to_page_dir(target_path, page_dir)})"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the cockpit's deterministic content diverges from a recompile at HEAD",
    )
    args = parser.parse_args()
    config = load_config(ROOT)
    page = build_page(ROOT, config)
    paths = WikiPaths(ROOT, config)
    target = paths.operation_page
    rel_target = paths.rel(target)
    if args.check:
        if not target.exists():
            print(f"{rel_target}: missing", file=sys.stderr)
            return 1
        committed = target.read_text(encoding="utf-8")
        if stable_cockpit_view(page) != stable_cockpit_view(committed):
            print(
                f"{rel_target} out of date: recompile with "
                "`python3 scripts/wiki_operation_compile.py --write` "
                "(the cockpit's deterministic content diverges from a recompile at HEAD).",
                file=sys.stderr,
            )
            return 1
        print(f"{rel_target}: cockpit deterministic content equal to a recompile at HEAD.")
        return 0
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        # Stewardship: recompiling the cockpit generates a score-event (idempotent per day).
        # event_type is FROZEN ledger vocabulary (score-events.jsonl); do not localize.
        record_event(
            paths.derived_root / "score-events.jsonl",
            event_type="recompilar_pagina_antiga",
            actor=config.owner_label,
            context=config.default_context,
            dedup_key=f"recompile-cockpit:{dt.date.today().isoformat()}",
        )
        print(rel_target)
        return 0
    print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
