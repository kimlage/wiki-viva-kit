#!/usr/bin/env python3
"""Build the DEMO wiki — the MOC of the modular-blocks process — AND the
GENESIS stages (the tutorial that starts from an empty world).

The cockpit demo is no longer hand-curated JSON. It is a real fixture-wiki
(the fictional consultant *Alex Rivera*) that exercises every template, block,
lens, the relations module, tools and the quadrant interior — compiled by the
SAME `build_snapshot` any wiki uses. Run this to regenerate everything:

    python3 scripts/wiki_build_demo.py

It writes the fixture markdown under docs/references/fixtures/demo-wiki/ (real,
browsable, committed), copies the kit's v2 contracts next to it, and renders:

  * the FULL demo snapshot into apps/wiki-cockpit/public/sample-snapshot/
  * one snapshot PER GENESIS STAGE into .../sample-snapshot/stages/<k>/ plus a
    stages.json manifest. Stage k is literally "what the cockpit shows when the
    wiki has exactly these pages and these blocks" — the tutorial swaps bundles;
    it NEVER simulates state client-side. The interface materializing between
    stages is the gating (data/surfaces.ts) reacting to the stack, not tutorial
    code.

Everything is fictional. If the demo does not show a capability, the phase that
introduced it is not done.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

KIT_ROOT = Path(__file__).resolve().parents[1]
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))
FIXTURE = KIT_ROOT / "docs/references/fixtures/demo-wiki"
OUT = KIT_ROOT / "apps/wiki-cockpit/public/sample-snapshot"

# A recent, fixed reference so the demo looks fresh with a couple of honest
# stale/overdue signals. Regenerating updates freshness to the real build date.
FRESH = "2026-07-03"
OLD = "2026-05-04"

# --- Genesis stages ----------------------------------------------------------
# Stage k = the wiki after tutorial step k. Pages enter at their stage; the
# ROOT's attachments grow (that is the whole point: templates ADD interface).
# Stage 8 must equal the full demo.
FINAL_STAGE = 8

# page_id -> first stage where the page exists. Anything not listed enters at
# the FINAL stage (the "explore the full world" ending).
STAGE_BY_PAGE: dict[str, int] = {
    "root-alex-rivera": 1,
    # Stage 3: the first area, with two leaves that populate q1/q2.
    "hub-financeiro": 3,
    "claim-custos-sobem": 3,
    "artifact-relatorio-recon": 3,
    # Stage 4: Marina (the seed of the mission — world knows, nothing asks).
    "person-marina-costa": 4,
    # Stage 6: the first live source (overdue on purpose).
    "source-banco-export": 6,
    # The source arrives WITH its history: the old ingestion event is what
    # makes "34 days overdue" an honest derivation, not a hardcoded label.
    "event-ingest-banco-2026-05": 6,
    # Stage 7: the system sees itself (meta pages as blueprints).
    "hub-sistema": 7,
    "block-library-lens": 7,
    "skill-agent-classify-quadrants": 7,
    "skill-agent-deep-read": 7,
    "skill-human-review-privacy": 7,
    "perspective-identity-intent": 7,
    "perspective-artifacts-evidence": 7,
    "perspective-roles-relationships": 7,
    "perspective-systems-processes": 7,
    "perspective-privacy-publication": 7,
    "perspective-financial": 7,
}


def root_attachments(stage: int) -> dict[str, Any]:
    """What the root PAGE has attached at each stage — the tutorial's arc."""
    blocks: list[dict[str, Any]] = []
    packages: list[str] = []
    if stage >= 2:
        blocks.append({"id": "wiki.block.quadrants.v1", "scope": "descendants"})
    if stage >= 4:
        blocks.append({"id": "wiki.block.relations.v1", "scope": "descendants"})
    if stage >= 5:
        packages.append("gamification")
    if stage >= FINAL_STAGE:
        blocks.append(
            {
                "id": "wiki.block.perspective_bundle.v1",
                "scope": "descendants",
                "config": {"required": ["perspective-privacy-publication"], "optional": ["perspective-financial"]},
            }
        )
    out: dict[str, Any] = {}
    if blocks:
        out["blocks"] = blocks
    if packages:
        out["packages"] = packages
    return out


# Per-stage manifest metadata: i18n keys live in the cockpit (genesis.*); the
# focus page is where the camera/tutorial points after the swap.
STAGE_FOCUS: dict[int, str] = {
    1: "root-alex-rivera",
    2: "root-alex-rivera",
    3: "hub-financeiro",
    4: "person-marina-costa",
    5: "root-alex-rivera",
    6: "source-banco-export",
    7: "hub-sistema",
    8: "root-alex-rivera",
}


def fm(**values: Any) -> dict[str, Any]:
    base = {"visibility": "private_self", "stale_after_days": 30}
    base.update(values)
    return base


def page(rel: str, front: dict[str, Any], body: str) -> tuple[str, dict[str, Any], str]:
    return rel, front, body


def render(front: dict[str, Any], body: str) -> str:
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{head}\n---\n\n{body.strip()}\n"


# ---------------------------------------------------------------------------
# The cast. Alex Rivera, independent consultant. All fictional.
# ---------------------------------------------------------------------------


def build_pages() -> list[tuple[str, dict[str, Any], str]]:
    pages: list[tuple[str, dict[str, Any], str]] = []

    # --- Root (the observatory) --------------------------------------------
    pages.append(
        page(
            "memories/index.md",
            fm(
                page_id="root-alex-rivera",
                page_type="root_entity",
                title="Alex Rivera",
                context="pessoal",
                root_entity_type="person",
                updated_at=FRESH,
                primary_contexts=["pessoal", "financeiro", "clientes", "estudio"],
                perspective_bundle_required=["perspective-privacy-publication"],
                perspective_bundle_optional=["perspective-financial"],
                identity={"landmark": "observatory", "motif": "rings", "ambient": "motes", "horizon_label": "title"},
            ),
            """
# Alex Rivera

Independent consultant. This root attaches the quadrants, the relations module
and the privacy boundary to everything below — so every area and every ingested
source is read through the same combined lenses.

## Identity and Scope

Design and AI-safety consulting for small teams. Values: clarity, evidence,
keeping a calm calendar.

## Integral Quadrant Map

- Q1 perception & intent · Q2 behavior & practice · Q3 relations & culture · Q4 systems & tools.
""",
        )
    )

    # --- Area hubs ----------------------------------------------------------
    pages.append(
        page(
            "memories/financeiro/index.md",
            fm(
                page_id="hub-financeiro",
                page_type="context_hub",
                title="Financeiro",
                context="financeiro",
                updated_at=FRESH,
                moc_parent="memories/index.md",
                identity={"landmark": "beacon", "motif": "ledger", "ambient": "none", "horizon_label": "context"},
                blocks=[
                    {"id": "wiki.block.ui_create.v1", "config": {"catalog": ["artifact", "claim", "decision", "tool"], "arrangement": "by_family"}},
                    {"id": "wiki.block.ui_missions.v1", "config": {"providers": ["stale", "template_conformity"]}},
                ],
            ),
            "# Financeiro\n\nMoney as evidence: budget, reconciliation, the bank source. The void tints with this area's hue; the beacon marks it.",
        )
    )
    pages.append(
        page(
            "memories/clientes/index.md",
            fm(
                page_id="hub-clientes",
                page_type="context_hub",
                title="Clientes",
                context="clientes",
                updated_at=FRESH,
                moc_parent="memories/index.md",
            ),
            "# Clientes\n\nEngagements, the people in them, the meetings and the deliverables.",
        )
    )
    pages.append(
        page(
            "memories/estudio/index.md",
            fm(
                page_id="hub-estudio",
                page_type="context_hub",
                title="Estúdio",
                context="estudio",
                updated_at=FRESH,
                moc_parent="memories/index.md",
            ),
            "# Estúdio\n\nThe craft: reading, references, insights. Home of the AI-safety library.",
        )
    )
    pages.append(
        page(
            "memories/sistema/index.md",
            fm(
                page_id="hub-sistema",
                page_type="context_hub",
                title="Sistema",
                context="sistema",
                updated_at=FRESH,
                moc_parent="memories/index.md",
                identity={"landmark": "engine", "motif": "grid", "ambient": "none", "horizon_label": "context"},
                blocks=[
                    {"id": "wiki.block.ui_create.v1", "config": {"catalog": ["template_block", "skill", "operational_rule", "perspective", "tool"]}},
                ],
            ),
            "# Sistema\n\nThe engine room: blocks, skills, perspectives, gates. The system sees itself with its own instruments.",
        )
    )

    # --- The client team (a plaza; quadrants re-centered) ------------------
    pages.append(
        page(
            "memories/clientes/product-ops/index.md",
            fm(
                page_id="holon-product-ops",
                page_type="holon",
                title="Product Ops Team",
                context="clientes",
                updated_at=FRESH,
                moc_parent="memories/clientes/index.md",
                identity={"landmark": "plaza", "motif": "grid", "ambient": "none", "horizon_label": "title"},
                blocks=[
                    {
                        "id": "wiki.block.quadrants.v1",
                        "scope": "descendants",
                        "config": {
                            "labels": {
                                "q1": "Intenção da equipe",
                                "q2": "Entregas e evidências",
                                "q3": "Relações e rituais",
                                "q4": "Sistemas e governança",
                            }
                        },
                    }
                ],
            ),
            "# Product Ops Team\n\nA client's team, re-centered: the same quadrant block, its own labels. The subgraph below sorts into the four lenses around this plaza.",
        )
    )

    # --- A project (the forge; trails home) --------------------------------
    pages.append(
        page(
            "memories/clientes/product-ops/atlas-launch/index.md",
            fm(
                page_id="project-atlas-launch",
                page_type="project",
                title="Atlas Launch",
                context="clientes",
                status="active",
                updated_at=FRESH,
                moc_parent="memories/clientes/product-ops/index.md",
                identity={"landmark": "forge", "motif": "orbits", "ambient": "none", "horizon_label": "title"},
            ),
            "# Atlas Launch\n\nA project looks like movement: trails is its home view, orbits its floor. (The optional decisions index subpage is intentionally absent — the mold shows it as an obligation.)",
        )
    )

    # --- A company root with its own recursive quadrants ------------------
    pages.append(
        page(
            "memories/empresas/clearpath-labs.md",
            fm(
                page_id="company-clearpath-labs",
                page_type="root_entity",
                title="Clearpath Labs",
                context="clientes",
                updated_at=FRESH,
                moc_parent="memories/index.md",
                root_entity_type="company",
                parent_projection={
                    "quadrant": "q4",
                    "sub_lens": "governanca",
                    "reason": "For Alex, a company is an external coordination system; inside itself it is the center.",
                },
                blocks=[
                    {
                        "id": "wiki.block.quadrants.v1",
                        "scope": "descendants",
                        "config": {
                            "labels": {
                                "q1": "Percepção e intenção da empresa",
                                "q2": "Entregas observáveis",
                                "q3": "Relações e cultura",
                                "q4": "Processos e governança",
                            }
                        },
                    }
                ],
            ),
            "# Clearpath Labs\n\nA fictional company root below Alex. From Alex's map it is Q4/system; when selected, the company becomes the center and its own intents, outputs, relations and systems split around it.",
        )
    )
    company_pages = [
        (
            "claim-clearpath-market-signal",
            "claim",
            "Clearpath sees onboarding friction",
            "subject_role",
            "perception",
            "percepcao",
            "Q1 inside the company: how Clearpath perceives the market.",
        ),
        (
            "decision-clearpath-enter-midmarket",
            "decision",
            "Clearpath enters the midmarket segment",
            "subject_role",
            "intention",
            "intencao",
            "Q1 inside the company: declared strategic intent.",
        ),
        (
            "artifact-clearpath-prototype",
            "artifact",
            "Clearpath onboarding prototype",
            "",
            "",
            "producao",
            "Q2 inside the company: something observable it produced.",
        ),
        (
            "meeting-clearpath-alignment",
            "meeting",
            "Clearpath alignment meeting",
            "",
            "",
            "encontros",
            "Q3 inside the company: shared meaning and people in the room.",
        ),
        (
            "process-clearpath-approval",
            "process",
            "Clearpath approval process",
            "",
            "",
            "processos",
            "Q4 inside the company: repeatable coordination.",
        ),
    ]
    for pid, ptype, title, role_key, role, sub_lens, body in company_pages:
        front = fm(
            page_id=pid,
            page_type=ptype,
            title=title,
            context="clientes",
            updated_at=FRESH,
            moc_parent="memories/empresas/clearpath-labs.md",
            subject_ref="company-clearpath-labs",
            sub_lens=sub_lens,
        )
        if role_key:
            front[role_key] = role
        pages.append(page(f"memories/empresas/clearpath/{pid}.md", front, f"# {title}\n\n{body}"))

    pages.extend(
        [
            page(
                "memories/empresas/clearpath/source-customer-interviews.md",
                fm(
                    page_id="source-clearpath-customer-interviews",
                    page_type="source",
                    title="Clearpath customer interviews",
                    context="clientes",
                    updated_at=FRESH,
                    moc_parent="memories/empresas/clearpath-labs.md",
                    subject_ref="company-clearpath-labs",
                    sub_lens="evidencias",
                    source_type="document",
                    platform="Interview notes",
                    owner="company-clearpath-labs",
                ),
                "# Clearpath customer interviews\n\nQ2 inside the company: an observable evidence source owned by the company root.",
            ),
            page(
                "memories/empresas/clearpath/dashboard-activation.md",
                fm(
                    page_id="dashboard-clearpath-activation",
                    page_type="dashboard",
                    title="Clearpath activation dashboard",
                    context="clientes",
                    updated_at=FRESH,
                    moc_parent="memories/empresas/clearpath-labs.md",
                    subject_ref="company-clearpath-labs",
                    sub_lens="metricas",
                ),
                "# Clearpath activation dashboard\n\nQ2 inside the company: a metric surface that shows what the company produced and measured.",
            ),
            page(
                "memories/empresas/clearpath/role-customer-success-lead.md",
                fm(
                    page_id="role-clearpath-customer-success-lead",
                    page_type="role",
                    title="Customer success lead",
                    context="clientes",
                    updated_at=FRESH,
                    moc_parent="memories/empresas/clearpath-labs.md",
                    subject_ref="company-clearpath-labs",
                    sub_lens="papeis",
                ),
                "# Customer success lead\n\nQ3 inside the company: a lived role with expectations and relationship context, not just an org-chart slot.",
            ),
            page(
                "memories/empresas/clearpath/rule-release-gate.md",
                fm(
                    page_id="rule-clearpath-release-gate",
                    page_type="operational_rule",
                    title="Clearpath release gate",
                    context="clientes",
                    updated_at=FRESH,
                    moc_parent="memories/empresas/clearpath-labs.md",
                    subject_ref="company-clearpath-labs",
                    sub_lens="governanca",
                ),
                "# Clearpath release gate\n\nQ4 inside the company: an explicit governance rule that coordinates release decisions.",
            ),
        ]
    )

    pages.append(
        page(
            "memories/empresas/clearpath/pulse-product.md",
            fm(
                page_id="product-clearpath-pulse",
                page_type="root_entity",
                title="Pulse Product",
                context="clientes",
                updated_at=FRESH,
                moc_parent="memories/empresas/clearpath-labs.md",
                root_entity_type="product",
                parent_projection={
                    "quadrant": "q2",
                    "sub_lens": "producao",
                    "reason": "For the company, a product is observable output; inside itself it is the center.",
                },
                blocks=[{"id": "wiki.block.quadrants.v1", "scope": "descendants"}],
            ),
            "# Pulse Product\n\nA product root inside Clearpath. For the company it is Q2/output; when selected, its own strategy and evidence are sorted around the product.",
        )
    )
    pages.append(
        page(
            "memories/empresas/clearpath/pulse/intent.md",
            fm(
                page_id="claim-pulse-activation",
                page_type="claim",
                title="Pulse improves activation",
                context="clientes",
                updated_at=FRESH,
                moc_parent="memories/empresas/clearpath/pulse-product.md",
                subject_ref="product-clearpath-pulse",
                subject_role="perception",
                sub_lens="percepcao",
            ),
            "# Pulse improves activation\n\nQ1 inside the product. From Alex it still passes through Clearpath as Q4; from Clearpath it passes through Pulse as Q2.",
        )
    )

    # --- The reference library (the shelf; quiet gamification) -------------
    pages.append(
        page(
            "memories/estudio/biblioteca-ai-safety/index.md",
            fm(
                page_id="library-ai-safety",
                page_type="context_hub",
                title="Biblioteca AI Safety",
                context="estudio",
                updated_at=FRESH,
                moc_parent="memories/estudio/index.md",
                identity={"landmark": "shelf", "motif": "shelves", "ambient": "motes", "horizon_label": "title"},
                blocks=[
                    {
                        "id": "wiki.block.quadrants.v1",
                        "scope": "descendants",
                        "config": {
                            "mode": "optional_lens",
                            "labels": {
                                "q1": "Ideias e pressupostos",
                                "q2": "Benchmarks e evidências",
                                "q3": "Autores e escolas",
                                "q4": "Instituições e standards",
                            },
                        },
                    },
                    {"id": "wiki.block.ui_views.v1", "config": {"default": "districts"}},
                    {"id": "wiki.block.ui_missions.v1", "config": {"quiet": True, "weather_contrib": False}},
                    {"id": "wiki.block.ui_create.v1", "config": {"catalog": ["artifact", "claim", "insight"]}},
                    {"id": "wiki.block.ui_intake.v1", "config": {"forms": ["promote_reference"]}},
                ],
            ),
            "# Biblioteca AI Safety\n\nA place with no pressure: missions are quiet, it does not push the weather. Same engine, opposite rules — the proof that gamification is modular.",
        )
    )

    # --- People (the relations module; Q3 rede) ----------------------------
    people = [
        {
            "id": "person-marina-costa",
            "title": "Marina Costa",
            "context": "estudio",
            # Anchored on the ROOT (not the estúdio hub): she enters at genesis
            # stage 4, before that hub exists — her chain must reach the root.
            "moc": "memories/index.md",
            "relationship": {"kind": "mentor", "since": "2019", "contact_cadence_days": 30, "channels_preferred": ["whatsapp"], "city": "Lisboa"},
            "dates": [{"kind": "anniversary", "date": "2019-06-02", "label": "primeiro projeto juntos"}],
            "topics": ["ai-safety", "cerâmica"],
            "last": OLD,  # overdue on purpose -> "Reconectar com Marina"
            "body": "Mentor since 2019. We talk roughly monthly — this page is overdue, which the world shows as an amber refresh, not a red alarm.",
        },
        {
            "id": "person-joao-mendes",
            "title": "João Mendes",
            "context": "clientes",
            "moc": "memories/clientes/product-ops/index.md",
            "relationship": {"kind": "client", "since": "2025", "contact_cadence_days": 14, "city": "Porto"},
            "last": FRESH,
            "body": "Client lead at Product Ops. Recently in a weekly sync.",
        },
        {
            "id": "person-bea-rivera",
            "title": "Bea Rivera",
            "context": "pessoal",
            "moc": "memories/index.md",
            "page_type": "root_entity",  # a person who is ALSO a root
            "relationship": {"kind": "partner", "since": "2016", "contact_cadence_days": 7},
            "last": FRESH,
            "body": "Business partner — and her own root (root_entity type person), with her own subgraph and quadrants. The relations module reads her as a person all the same.",
        },
        {
            "id": "person-rita-souza",
            "title": "Rita Souza",
            "context": "financeiro",
            "moc": "memories/financeiro/index.md",
            "relationship": {"kind": "vendor", "contact_cadence_days": 60},
            "last": FRESH,
            "body": "Accountant. Handles the yearly reconciliation.",
        },
        {
            "id": "person-lia-fontes",
            "title": "Lia Fontes",
            "context": "pessoal",
            "moc": "memories/index.md",
            "relationship": {"kind": "friend", "contact_cadence_days": 45},
            "dates": [{"kind": "birthday", "date": "2026-07-11"}],  # ~upcoming
            "last": FRESH,
            "body": "Old friend. Birthday coming up — the world raises an upcoming-date mission.",
        },
        {
            "id": "person-caio-prado",
            "title": "Caio Prado",
            "context": "clientes",
            "moc": "memories/clientes/index.md",
            "relationship": {"kind": "vendor", "contact_cadence_days": 90},
            "commitments": [{"ref": "action-enviar-proposta", "due": "2026-07-10"}],
            "last": FRESH,
            "body": "Freelance developer. There is an open commitment to send a proposal.",
        },
    ]
    for person in people:
        front = fm(
            page_id=person["id"],
            page_type=person.get("page_type", "person"),
            title=person["title"],
            context=person["context"],
            updated_at=person["last"],
            stale_after_days=45,
            moc_parent=person["moc"],
        )
        for key in ("relationship", "dates", "commitments", "topics"):
            if key in person:
                front[key] = person[key]
        if person.get("page_type") == "root_entity":
            front["root_entity_type"] = "person"
        pages.append(page(f"memories/people/{person['id']}.md", front, f"# {person['title']}\n\n{person['body']}"))

    # --- Tools (Q4 ferramentas) --------------------------------------------
    tools = [
        ("tool-obsidian", "Obsidian", "pessoal", "Obsidian", "vault local (no secret)", "$0"),
        ("tool-google-drive", "Google Drive", "sistema", "Google", "OAuth via wiki-raw-drive (pointer only)", "Workspace"),
        ("tool-banco-app", "App do Banco", "financeiro", "Banco", "exported statements only", "$0"),
    ]
    for tid, title, context, platform, pointer, cost in tools:
        pages.append(
            page(
                f"memories/tools/{tid}.md",
                fm(
                    page_id=tid,
                    page_type="tool",
                    title=title,
                    context=context,
                    updated_at=FRESH,
                    moc_parent="memories/index.md",
                    platform=platform,
                    access_pointer=pointer,
                    cost=cost,
                    status="active",
                ),
                f"# {title}\n\n## What it is\n\nA tool the practice uses.\n\n## Access and cost\n\n- Access pointer: {pointer}\n- Cost: {cost}",
            )
        )

    # --- Sources (crystal spires; content by ingestion) --------------------
    sources = [
        ("source-banco-export", "Extrato do Banco", "financeiro", "Banco", "memories/financeiro/index.md"),
        ("source-agenda", "Agenda", "pessoal", "Google Calendar", "memories/index.md"),
        ("source-chat-export", "Export do Chat", "clientes", "WhatsApp", "memories/clientes/index.md"),
    ]
    for sid, title, context, platform, moc in sources:
        pages.append(
            page(
                f"memories/sources/{sid}.md",
                fm(
                    page_id=sid,
                    page_type="source",
                    title=title,
                    context=context,
                    updated_at=FRESH if sid != "source-banco-export" else OLD,
                    moc_parent=moc,
                    source_type="live",
                    platform=platform,
                    owner="root-alex-rivera",
                ),
                f"# {title}\n\nA live source. Its content is born by ingestion — manual creation under it is off. (The bank export is intentionally overdue.)",
            )
        )

    # --- Ingestion events: the wiki's own record of syncs ------------------
    # Each source's "last synced" is DERIVED from its newest ingestion event
    # (source_refs) — a wiki with ingested content never reads "never synced".
    # The bank export's newest event is OLD on purpose: 34+ days overdue is the
    # story beat the gamification package turns into a sync mission.
    ingestion_events = [
        ("event-ingest-banco-2026-05", "Ingestão: extrato do banco (maio)", OLD, "source-banco-export",
         "Normalized import of the bank statement. The claim about cloud costs and the reconciliation report were born here."),
        ("event-ingest-chat-2026-07", "Ingestão: export do chat", FRESH, "source-chat-export",
         "Normalized import of the client chat export — meetings and people references updated."),
        ("event-ingest-agenda-2026-07", "Ingestão: agenda", FRESH, "source-agenda",
         "Normalized import of the calendar — encounters and cadences refreshed."),
    ]
    for eid, title, when, source_ref, body in ingestion_events:
        pages.append(
            page(
                f"memories/system/ingestion/events/{eid}.md",
                fm(
                    page_id=eid,
                    page_type="ingestion_event",
                    title=title,
                    context="sistema",
                    updated_at=when,
                    stale_after_days="365",  # a dated event is history, never "stale"
                    moc_parent="memories/index.md",
                    source_refs=[source_ref],
                ),
                f"# {title}\n\n{body}\n\n## Source\n\n- Source: `{source_ref}`\n- Normalized event: this page IS the record of the sync.",
            )
        )

    # --- Leaves that populate the quadrant interiors -----------------------
    leaves = [
        # q1 perception
        ("claim-custos-sobem", "claim", "Custos de nuvem subiram 18%", "financeiro", "memories/financeiro/index.md", {"source_refs": ["source-banco-export"]}, "percepcao"),
        ("insight-calendario-calmo", "insight", "Calendário calmo rende trabalho melhor", "pessoal", "memories/index.md", {}, "percepcao"),
        # Content revalidation: a meeting note is a RELATION record.
        ("journal-2026-07-02", "journal_entry", "Nota do dia — sync com João", "clientes", "memories/clientes/index.md", {"home_quadrant": "relacoes"}, "encontros"),
        # q1 intent
        ("decision-precos", "decision", "Reajustar preço de consultoria", "clientes", "memories/clientes/index.md", {"status": "active"}, "intencao"),
        ("decision-onboarding", "decision", "Padronizar onboarding de cliente", "clientes", "memories/clientes/product-ops/index.md", {"status": "active"}, "intencao"),
        # q2 behavior/production
        # Content revalidation 2026-07-07: an OPEN commitment is intent, not
        # produced work — home_quadrant carries the content-level judgment.
        ("action-enviar-proposta", "action", "Enviar proposta para Caio", "clientes", "memories/clientes/index.md", {"status": "open", "home_quadrant": "intencao"}, "intencao"),
        ("artifact-dashboard-atlas", "artifact", "Dashboard do Atlas", "clientes", "memories/clientes/product-ops/atlas-launch/index.md", {}, "producao"),
        ("artifact-relatorio-recon", "artifact", "Relatório de reconciliação", "financeiro", "memories/financeiro/index.md", {"source_refs": ["source-banco-export"]}, "producao"),
        # q3 relations/meetings/culture
        ("meeting-weekly-sync", "meeting", "Weekly sync — Product Ops", "clientes", "memories/clientes/product-ops/index.md", {"participants": ["person-joao-mendes"]}, "encontros"),
        ("role-consultora", "role", "Consultora líder", "clientes", "memories/clientes/product-ops/index.md", {}, "pessoas"),
        # q4 systems/process/governance
        ("process-fechamento-mensal", "process", "Fechamento mensal", "financeiro", "memories/financeiro/index.md", {"cadence": "monthly"}, "processos"),
        # Content revalidation: a publication gate is GOVERNANCE (systems).
        ("rule-nada-publica-sem-review", "operational_rule", "Nada publica sem review humano", "sistema", "memories/sistema/index.md", {"home_quadrant": "sistemas"}, "governanca"),
        # q0 structural
        ("idx-decisoes", "ontology_index", "Índice de decisões", "clientes", "memories/clientes/index.md", {}, None),
        # library leaves (optional-lens quadrants)
        ("claim-scaling-laws", "claim", "Scaling laws seguem valendo em 2026", "estudio", "memories/estudio/biblioteca-ai-safety/index.md", {}, "percepcao"),
        ("artifact-benchmark-safety", "artifact", "Benchmark de safety evals", "estudio", "memories/estudio/biblioteca-ai-safety/index.md", {}, "producao"),
    ]
    for lid, ptype, title, context, moc, extra, sublens in leaves:
        front = fm(page_id=lid, page_type=ptype, title=title, context=context, updated_at=FRESH, moc_parent=moc)
        front.update(extra)
        if sublens:
            front["sub_lens"] = sublens
        body = f"# {title}\n\n"
        # Make the weekly sync link João (drives his last_interaction) and the
        # journal too — so the relations module reads real interactions.
        if lid == "meeting-weekly-sync":
            body += "Sync with [João Mendes](../../people/person-joao-mendes.md). Decisions and follow-ups below."
        elif lid == "journal-2026-07-02":
            body += "Quick sync with [João Mendes](../people/person-joao-mendes.md); nothing blocking."
        elif lid == "action-enviar-proposta":
            body += "Proposal promised to [Caio Prado](../people/person-caio-prado.md)."
        else:
            body += "Content that lands in its quadrant interior."
        pages.append(page(f"memories/{_leaf_dir(ptype)}/{lid}.md", front, body))

    # --- Perspectives (the lens content blocks reference) ------------------
    perspectives = [
        ("perspective-identity-intent", "Identidade e intenção", "Q1: como é percebido e por que existe."),
        ("perspective-artifacts-evidence", "Artefatos e evidência", "Q2: o que é feito e evidenciado."),
        ("perspective-roles-relationships", "Papéis e relações", "Q3: quem está junto e o significado compartilhado."),
        ("perspective-systems-processes", "Sistemas e processos", "Q4: o que coordena — ferramentas, processos, fontes."),
        ("perspective-privacy-publication", "Privacidade e publicação", "A fronteira público/privado."),
        ("perspective-financial", "Financeiro", "Fatos financeiros e de conciliação."),
    ]
    for pid, title, concern in perspectives:
        pages.append(
            page(
                f"memories/sistema/perspectivas/{pid}.md",
                fm(
                    page_id=pid,
                    page_type="perspective",
                    title=title,
                    context="sistema",
                    updated_at=FRESH,
                    moc_parent="memories/sistema/index.md",
                ),
                f"# {title}\n\n## Concern\n\n{concern}\n\n## Extraction Questions\n\n- What does this lens ask of a source?\n\n## Target Pages\n\n- The pages this lens tends to update.\n\n## Correspondence Rules\n\n- Classify the fact, not the file.",
            )
        )

    # --- System pages: blocks and skills as pages (dogfooding) -------------
    pages.append(
        page(
            "memories/sistema/blocks/block-library-lens.md",
            fm(
                page_id="block-library-lens",
                page_type="template_block",
                title="Lente de quadrantes para bibliotecas",
                context="sistema",
                updated_at=FRESH,
                moc_parent="memories/sistema/index.md",
                parent_projection={
                    "quadrant": "q4",
                    "sub_lens": "governanca",
                    "reason": "Reusable interpretation blueprint inside the system layer.",
                },
                block={
                    "block_id": "wiki.block.quadrants_lens_library.v1",
                    "family": "quadrants",
                    "kind": "interpretation",
                    "extends": "wiki.block.quadrants.v1",
                    "scope": {"default_mode": "descendants"},
                    "anchors": ["context_hub"],
                    "config": {"mode": "optional_lens"},
                },
                blocks=[
                    {
                        "id": "wiki.block.quadrants.v1",
                        "scope": "descendants",
                        "config": {
                            "labels": {
                                "q1": "Propósito do template",
                                "q2": "Exemplos e artefatos",
                                "q3": "Revisão compartilhada",
                                "q4": "Campos e governança",
                            }
                        },
                    }
                ],
            ),
            "# Lente de quadrantes para bibliotecas\n\n## Purpose\n\nSpecializes the kit quadrants block for reference libraries — navigate without forcing ingestion.\n\n## Contract\n\n- Inherits the canonical AQAL lenses; only relabels and softens to optional.",
        )
    )
    template_support = [
        (
            "memories/claims/template-library-purpose.md",
            "claim-template-library-purpose",
            "claim",
            "Propósito da lente de biblioteca",
            "interior_intent",
            "# Propósito da lente de biblioteca\n\nThe template states why a library should keep quadrants optional but visible.",
        ),
        (
            "memories/artifacts/template-library-example.md",
            "artifact-template-library-example",
            "artifact",
            "Exemplo de biblioteca classificada",
            "artifact_output",
            "# Exemplo de biblioteca classificada\n\nA synthetic filled example showing how a reference item lands in the template.",
        ),
        (
            "memories/meetings/template-library-review.md",
            "meeting-template-library-review",
            "meeting",
            "Revisão da lente de biblioteca",
            "meeting_shared_meaning",
            "# Revisão da lente de biblioteca\n\nA human review ritual around whether the template should remain optional.",
        ),
        (
            "memories/processes/template-library-governance.md",
            "process-template-library-governance",
            "process",
            "Governança da lente de biblioteca",
            "system_process",
            "# Governança da lente de biblioteca\n\nThe fields and publication rules that keep this template reusable.",
        ),
    ]
    for rel, pid, ptype, title, role, body in template_support:
        pages.append(
            page(
                rel,
                fm(
                    page_id=pid,
                    page_type=ptype,
                    title=title,
                    context="sistema",
                    updated_at=FRESH,
                    stale_after_days=45,
                    moc_parent="memories/sistema/blocks/block-library-lens.md",
                    source_refs=[],
                    subject_ref="block-library-lens",
                    subject_role=role,
                ),
                body,
            )
        )
    skills = [
        ("skill-agent-classify-quadrants", "Classify content by quadrants", "agent", "brief"),
        ("skill-agent-deep-read", "Deep read a source", "agent", "brief"),
        ("skill-human-review-privacy", "Review privacy before publishing", "human", "checklist"),
    ]
    for sid, title, stype, execution in skills:
        pages.append(
            page(
                f"memories/sistema/skills/{sid}.md",
                fm(
                    page_id=sid,
                    page_type="skill",
                    title=title,
                    context="sistema",
                    updated_at=FRESH,
                    moc_parent="memories/sistema/index.md",
                    skill_type=stype,
                    execution=execution,
                    writes="proposal_branch_only",
                ),
                f"# {title}\n\n## Purpose\n\n{title}.\n\n## Contract\n\n- Writes stay proposal-branch-only; no secrets.\n\n## Playbook\n\n1. Compose a brief; hand it to the approval ladder.",
            )
        )

    return pages


def _leaf_dir(page_type: str) -> str:
    return {
        "claim": "claims",
        "insight": "insights",
        "journal_entry": "journal",
        "decision": "decisions",
        "action": "actions",
        "artifact": "artifacts",
        "meeting": "meetings",
        "role": "roles",
        "process": "processes",
        "operational_rule": "rules",
        "ontology_index": "indexes",
    }.get(page_type, "notes")


def _stage_of(front: dict[str, Any]) -> int:
    return STAGE_BY_PAGE.get(str(front.get("page_id") or ""), FINAL_STAGE)


def _neutralize_repo_state(out_dir: Path) -> None:
    """The fixture lives INSIDE the kit repo, so build_snapshot's git walk finds
    the kit's real worktree — leaking the developer's uncommitted files into the
    demo (an Approve badge of 135 in a fictional world is a lie). The demo is a
    SELF-CONTAINED universe: clean tree, empty diff, honest zero."""
    import json

    git_path = out_dir / "git.json"
    if git_path.exists():
        git = json.loads(git_path.read_text(encoding="utf-8"))
        git["current_branch"] = git.get("default_branch") or "main"
        git["worktree"] = {"clean": True, "changed_files": []}
        git["proposal"] = {
            "is_proposal_branch": False,
            "theme": "",
            "draft_pr_url": None,
            "human_gate_state": "clean",
        }
        git_path.write_text(json.dumps(git, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diff_path = out_dir / "diff.json"
    if diff_path.exists():
        diff = json.loads(diff_path.read_text(encoding="utf-8"))
        diff["files"] = []
        diff["summary"] = {
            "file_count": 0,
            "branch_file_count": 0,
            "working_tree_file_count": 0,
            "insertions": 0,
            "deletions": 0,
            "status_counts": {},
            "privacy_review_required": False,
        }
        diff_path.write_text(json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_fixture(target: Path, stage: int = FINAL_STAGE) -> list[str]:
    """Write the fixture-wiki for `stage` into `target`. Returns page_ids."""
    memories = target / "memories"
    if memories.exists():
        shutil.rmtree(memories)
    written: list[str] = []
    for rel, front, body in build_pages():
        if _stage_of(front) > stage:
            continue
        if str(front.get("page_id")) == "root-alex-rivera":
            front = {**front, **root_attachments(stage)}
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(front, body), encoding="utf-8")
        written.append(str(front["page_id"]))
    # Even the empty world (stage 0) is a valid wiki tree.
    memories.mkdir(parents=True, exist_ok=True)
    # The demo uses the KIT's v2 contracts verbatim.
    for name in ("wiki.templates.yaml", "wiki.page-types.yaml"):
        shutil.copy(KIT_ROOT / name, target / name)
    (target / "wiki.config.yaml").write_text(
        "repo_id: wiki-viva-demo\n"
        "language: en\n"
        "default_context: pessoal\n"
        "contexts: [pessoal, financeiro, clientes, estudio, sistema]\n"
        "root_entity:\n"
        "  page: memories/index.md\n"
        "  entity_type: person\n",
        encoding="utf-8",
    )
    return written


def build_stage_snapshots() -> dict[str, Any]:
    """One REAL snapshot per genesis stage under OUT/stages/<k>/ + manifest."""
    import tempfile

    from wiki_core.config import load_config
    from wiki_core.web.snapshot import write_snapshot

    stages_dir = OUT / "stages"
    if stages_dir.exists():
        shutil.rmtree(stages_dir)
    manifest: dict[str, Any] = {"schema_version": "wiki_genesis_stages.v1", "final_stage": FINAL_STAGE, "stages": []}
    previous: set[str] = set()
    for stage in range(FINAL_STAGE + 1):
        with tempfile.TemporaryDirectory(prefix=f"wiki-demo-stage-{stage}-") as tmp:
            tmp_root = Path(tmp)
            page_ids = set(write_fixture(tmp_root, stage))
            config = load_config(tmp_root)
            out_dir = stages_dir / str(stage)
            write_snapshot(tmp_root, out_dir, config, clean=True, mode="static", content_sidecars=True)
            _neutralize_repo_state(out_dir)
            manifest["stages"].append(
                {
                    "stage": stage,
                    "dir": f"stages/{stage}",
                    "focus": STAGE_FOCUS.get(stage, ""),
                    "page_count": len(page_ids),
                    "added_pages": sorted(page_ids - previous),
                    "root_attachments": root_attachments(stage) if stage >= 1 else {},
                }
            )
            previous = page_ids
    import json

    (stages_dir / "stages.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    from wiki_core.config import load_config
    from wiki_core.web.snapshot import write_snapshot

    write_fixture(FIXTURE, FINAL_STAGE)
    config = load_config(FIXTURE)
    written = write_snapshot(FIXTURE, OUT, config, clean=True, mode="static", content_sidecars=True)
    _neutralize_repo_state(OUT)
    pages = len(list((FIXTURE / "memories").rglob("*.md")))
    manifest = build_stage_snapshots()
    print(
        f"demo: {pages} pages -> {len(written)} snapshot files in {OUT.relative_to(KIT_ROOT)}"
        f" + {len(manifest['stages'])} genesis stages"
    )


if __name__ == "__main__":
    main()
