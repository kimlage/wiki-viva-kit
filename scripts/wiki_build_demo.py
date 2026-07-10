#!/usr/bin/env python3
"""Build the DEMO wiki — the MOC of the modular-blocks process — AND the
GENESIS stages (the tutorial that starts from an empty world).

The cockpit demo is no longer hand-curated JSON. It is a real fixture-wiki
(the fictional consultant *Alex Rivera*) that exercises every template, block,
lens, the relations module, tools and the quadrant interior — compiled by the
SAME `build_snapshot` any wiki uses. Run this to regenerate everything:

    python3 scripts/wiki_build_demo.py

It writes the complete authored fixture markdown under
docs/references/fixtures/demo-wiki/ (real, browsable, committed), copies the
kit's v2 contracts next to it, and renders:

  * the instructional normal_operations snapshot into
    apps/wiki-cockpit/public/sample-snapshot/
  * the explicit dense_stress load-test snapshot into
    .../sample-snapshot/scenarios/dense_stress/
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

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import yaml

KIT_ROOT = Path(__file__).resolve().parents[1]
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))
FIXTURE = KIT_ROOT / "docs/references/fixtures/demo-wiki"
OUT = KIT_ROOT / "apps/wiki-cockpit/public/sample-snapshot"
SCENARIOS_DIR = FIXTURE / "scenarios"

# Demo snapshots are release artifacts, not clocks.  A fixed instant keeps the
# generated bundle byte-for-byte reproducible and makes freshness assertions a
# conscious fixture edit instead of a surprise on tomorrow's CI run.
DEMO_REFERENCE_DATE = dt.date(2026, 7, 9)
DEMO_GENERATED_AT = "2026-07-09T00:00:00Z"
DEMO_FIXTURE_ID = "wiki-viva-demo-v8"
DEMO_SEED = 8008

REQUIRED_SCENARIOS = (
    "walking_skeleton",
    "normal_operations",
    "dense_stress",
    "source_lifecycle",
    "failures",
    "compatibility",
    "accessibility",
)

DEFAULT_DEMO_SCENARIO = "normal_operations"
EXPLICIT_SNAPSHOT_SCENARIOS = ("dense_stress",)

GENERATED_FIXTURE_CONFIGS = (
    "wiki.config.yaml",
    "wiki.page-types.yaml",
    "wiki.templates.yaml",
)

# Dates are evaluated against DEMO_REFERENCE_DATE so fresh/stale/overdue states
# remain stable until the fixture contract is intentionally advanced.
FRESH = "2026-07-03"
OLD = "2026-05-04"

# --- Genesis stages ----------------------------------------------------------
# Stage k = the wiki after tutorial step k. Pages enter at their stage; the
# ROOT's attachments grow (that is the whole point: templates ADD interface).
# Stage 8 must equal the default instructional demo. The complete authored cast
# remains in the fixture and dense pressure has its own explicit snapshot.
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


def page_id_hash(page_ids: Sequence[str]) -> str:
    """Stable identity for a scenario's exact semantic page set."""
    return hashlib.sha256("\n".join(sorted(set(page_ids))).encode("utf-8")).hexdigest()


def load_scenario_manifests(scenarios_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and minimally validate the public v8 scenario registry.

    The YAML files are authored inputs.  Keeping the loader here makes the
    manifest executable: tests and future screenshot runners consume the same
    scenario contract instead of maintaining a second matrix in code.
    """
    root = scenarios_dir or SCENARIOS_DIR
    index_path = root / "manifest.yaml"
    if not index_path.is_file():
        raise ValueError(f"demo scenario index is missing: {index_path}")
    index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if index.get("schema_version") != "wiki_demo_scenarios.v1":
        raise ValueError("demo scenario index must use wiki_demo_scenarios.v1")
    if index.get("fixture_id") != DEMO_FIXTURE_ID:
        raise ValueError(f"demo scenario fixture_id must be {DEMO_FIXTURE_ID}")

    entries = index.get("scenario_manifests")
    if not isinstance(entries, list) or not entries:
        raise ValueError("demo scenario index must declare scenario_manifests")

    manifests: dict[str, dict[str, Any]] = {}
    root_resolved = root.resolve()
    for relative in entries:
        path = (root / str(relative)).resolve()
        if path.parent != root_resolved:
            raise ValueError(f"scenario manifest must be a direct child of {root}: {relative}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        scenario_id = str(payload.get("scenario_id") or "")
        if payload.get("schema_version") != "wiki_demo_scenario.v1":
            raise ValueError(f"{relative}: expected wiki_demo_scenario.v1")
        if payload.get("fixture_id") != DEMO_FIXTURE_ID:
            raise ValueError(f"{relative}: fixture_id must be {DEMO_FIXTURE_ID}")
        if not scenario_id or path.name != f"{scenario_id}.yaml":
            raise ValueError(f"{relative}: file name and scenario_id must agree")
        if not isinstance(payload.get("seed"), int) or int(payload["seed"]) < 0:
            raise ValueError(f"{relative}: seed must be a non-negative integer")
        for required in (
            "builder",
            "source_pages",
            "composition",
            "expected",
            "versions",
            "canonical_routes",
            "interactions",
            "automated_assertions",
            "visual",
            "expected_warnings",
            "expected_failures",
            "generated_files",
            "regeneration_command",
        ):
            if required not in payload:
                raise ValueError(f"{relative}: missing required field {required}")
        if scenario_id in manifests:
            raise ValueError(f"duplicate demo scenario: {scenario_id}")
        manifests[scenario_id] = payload

    missing = sorted(set(REQUIRED_SCENARIOS) - manifests.keys())
    unexpected = sorted(manifests.keys() - set(REQUIRED_SCENARIOS))
    if missing or unexpected:
        raise ValueError(f"demo scenario registry mismatch; missing={missing}, unexpected={unexpected}")
    return manifests


def scenario_page_ids(
    scenario_id: str,
    *,
    pages: list[tuple[str, dict[str, Any], str]] | None = None,
    manifests: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Resolve a scenario's composable selectors against the canonical cast."""
    pages = build_pages() if pages is None else pages
    manifests = load_scenario_manifests() if manifests is None else manifests
    if scenario_id not in manifests:
        raise ValueError(f"unknown demo scenario: {scenario_id}")
    composition = manifests[scenario_id].get("composition") or {}
    by_id = {str(front.get("page_id") or ""): (rel, front, body) for rel, front, body in pages}
    if len(by_id) != len(pages) or "" in by_id:
        raise ValueError("demo pages must have unique non-empty page_id values")

    selected: set[str] = set(by_id) if composition.get("include_all") is True else set()
    explicit = {str(item) for item in composition.get("include_ids") or []}
    unknown = sorted(explicit - by_id.keys())
    if unknown:
        raise ValueError(f"{scenario_id}: unknown include_ids: {unknown}")
    selected.update(explicit)

    prefixes = tuple(str(item) for item in composition.get("include_id_prefixes") or [])
    excluded_prefixes = tuple(str(item) for item in composition.get("exclude_id_prefixes") or [])
    page_types = {str(item) for item in composition.get("include_page_types") or []}
    for page_id, (_, front, _) in by_id.items():
        if prefixes and page_id.startswith(prefixes):
            selected.add(page_id)
        if page_types and str(front.get("page_type") or "") in page_types:
            selected.add(page_id)
    if excluded_prefixes:
        selected = {page_id for page_id in selected if not page_id.startswith(excluded_prefixes)}
    return sorted(selected)


def build_scenario_pages(scenario_id: str) -> list[tuple[str, dict[str, Any], str]]:
    """Materialize one scenario from the shared domain cast."""
    pages = build_pages()
    selected = set(scenario_page_ids(scenario_id, pages=pages))
    return [item for item in pages if str(item[1].get("page_id") or "") in selected]


def validate_scenario_manifests() -> dict[str, dict[str, Any]]:
    """Prove that every declared count/hash still matches its builder inputs."""
    manifests = load_scenario_manifests()
    pages = build_pages()
    for scenario_id, manifest in manifests.items():
        page_ids = scenario_page_ids(scenario_id, pages=pages, manifests=manifests)
        expected = manifest.get("expected") or {}
        if expected.get("page_count") != len(page_ids):
            raise ValueError(
                f"{scenario_id}: expected page_count {expected.get('page_count')}, built {len(page_ids)}"
            )
        actual_hash = page_id_hash(page_ids)
        if expected.get("page_id_sha256") != actual_hash:
            raise ValueError(
                f"{scenario_id}: expected page_id_sha256 {expected.get('page_id_sha256')}, built {actual_hash}"
            )
    return manifests


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
        ("source-inbox-capture", "Inbox capture stream", "pessoal", "Inbox", "memories/index.md"),
        ("source-notes-vault", "Notes vault index", "pessoal", "Markdown vault", "memories/index.md"),
        ("source-reference-folder", "Reference folder mirror", "estudio", "Drive folder", "memories/index.md"),
        ("source-reading-queue", "Reading queue export", "estudio", "Read-it-later", "memories/index.md"),
        ("source-calendar-archive", "Calendar archive", "pessoal", "Calendar", "memories/index.md"),
        ("source-decision-log", "Decision log export", "sistema", "Decision ledger", "memories/index.md"),
        ("source-template-registry", "Template registry snapshot", "sistema", "Template registry", "memories/index.md"),
        ("source-health-checks", "Health checks output", "sistema", "Checks", "memories/index.md"),
        ("source-action-ledger", "Action ledger export", "sistema", "Action tracker", "memories/index.md"),
        ("source-publication-queue", "Publication queue", "sistema", "Review queue", "memories/index.md"),
        ("source-evidence-ledger", "Evidence ledger export", "sistema", "Evidence ledger", "memories/index.md"),
        ("source-relation-cadence", "Relation cadence export", "pessoal", "Relations", "memories/index.md"),
        ("source-chat-export", "Export do Chat", "clientes", "WhatsApp", "memories/clientes/index.md"),
        ("source-product-analytics", "Product analytics export", "clientes", "Analytics", "memories/clientes/index.md"),
        ("source-support-tickets", "Support tickets export", "clientes", "Helpdesk", "memories/clientes/index.md"),
        ("source-crm-accounts", "CRM accounts export", "clientes", "CRM", "memories/clientes/index.md"),
        ("source-sales-pipeline", "Sales pipeline export", "clientes", "CRM", "memories/clientes/index.md"),
        ("source-call-recordings", "Call recordings archive", "clientes", "Call archive", "memories/clientes/index.md"),
        ("source-nps-surveys", "NPS survey export", "clientes", "Survey tool", "memories/clientes/index.md"),
        ("source-feature-flags", "Feature flag audit", "clientes", "Feature flags", "memories/clientes/product-ops/index.md"),
        ("source-usage-warehouse", "Usage warehouse extract", "clientes", "Warehouse", "memories/clientes/product-ops/index.md"),
        ("source-release-notes", "Release notes archive", "clientes", "Docs", "memories/clientes/product-ops/index.md"),
        ("source-error-traces", "Error trace export", "clientes", "Observability", "memories/clientes/product-ops/index.md"),
        ("source-clearpath-billing", "Clearpath billing feed", "clientes", "Billing", "memories/empresas/clearpath-labs.md"),
        ("source-clearpath-support", "Clearpath support feed", "clientes", "Helpdesk", "memories/empresas/clearpath-labs.md"),
        ("source-clearpath-roadmap", "Clearpath roadmap archive", "clientes", "Roadmap", "memories/empresas/clearpath-labs.md"),
        ("source-clearpath-risk-log", "Clearpath risk log", "clientes", "Risk register", "memories/empresas/clearpath-labs.md"),
    ]
    lifecycle_fixtures: dict[str, dict[str, Any]] = {
        "source-action-ledger": {
            "region_expectations": {
                "intencao": {
                    "state": "required",
                    "basis": "The action-ledger source contract requires at least one declared intent or reviewed no-change receipt.",
                    "expected_type_hints": ["action"],
                    "expected_action_hints": ["review_source_contract"],
                    "next_interaction": "seedPage",
                }
            },
            "source_lifecycle": {
                "state": "configured", "freshness_state": "never_synced", "last_attempt_state": "never",
                "pipeline_stage": "configured", "adoption_state": "pending",
            }
        },
        "source-reference-folder": {
            "region_expectations": {
                "intencao": {
                    "state": "optional",
                    "basis": "The reference folder may be evidence-only; an empty intent lens is explicitly healthy.",
                    "next_interaction": "openDock:source",
                }
            },
            "source_lifecycle": {
                "state": "ready", "freshness_state": "never_synced", "last_attempt_state": "never",
                "pipeline_stage": "configured", "adoption_state": "pending",
            }
        },
        "source-release-notes": {
            "sync": {"last_run_at": FRESH, "last_status": "running", "last_event_ref": ""},
            "source_lifecycle": {
                "state": "syncing", "freshness_state": "fresh", "last_attempt_state": "ok",
                "pipeline_stage": "indexed", "pipeline_stage_timestamps": {"manifested": FRESH, "extracted": FRESH, "indexed": FRESH},
                "adoption_state": "pending", "last_attempt_at": FRESH, "raw_artifact_count": 2,
                "secret_safe_log_refs": ["logs/demo/source-release-notes-attempt"],
            },
        },
        "source-chat-export": {
            "sync": {"last_run_at": FRESH, "last_status": "ok", "last_event_ref": "memories/system/ingestion/events/event-ingest-chat-2026-07.md"},
            "source_lifecycle": {
                "state": "proposed", "freshness_state": "fresh", "last_attempt_state": "ok",
                "pipeline_stage": "proposal_ready", "adoption_state": "pending", "last_sync_success_at": FRESH,
                "last_attempt_at": FRESH, "proposal_ids": ["event-ingest-chat-2026-07"], "raw_artifact_count": 1,
                "secret_safe_log_refs": ["logs/demo/source-chat-export-attempt"],
            },
        },
        "source-product-analytics": {
            "sync": {"last_run_at": FRESH, "last_status": "ok", "last_event_ref": "memories/system/ingestion/events/event-ingest-product-analytics-2026-07.md"},
            "source_lifecycle": {
                "state": "ingested", "freshness_state": "fresh", "last_attempt_state": "ok",
                "pipeline_stage": "complete", "adoption_state": "accepted", "accepted_ref": "demo-sha:product-analytics-accepted",
                "last_sync_success_at": FRESH, "last_ingested_at": FRESH, "last_attempt_at": FRESH,
                "emitted_page_ids": ["dashboard-clearpath-activation"],
                "proposal_ids": ["proposal-ingest-product-analytics-2026-07"], "raw_artifact_count": 1,
                "secret_safe_log_refs": ["logs/demo/source-product-analytics-attempt"],
            },
        },
        "source-support-tickets": {
            "sync": {"last_run_at": OLD, "last_status": "ok", "last_event_ref": "memories/system/ingestion/events/event-ingest-support-tickets-2026-06.md"},
            "source_lifecycle": {
                "state": "proposed", "freshness_state": "stale", "last_attempt_state": "ok",
                "pipeline_stage": "proposal_ready", "adoption_state": "pending", "last_sync_success_at": OLD,
                "last_attempt_at": OLD, "proposal_ids": ["event-ingest-support-tickets-2026-06"],
                "raw_artifact_count": 1, "secret_safe_log_refs": ["logs/demo/source-support-tickets-attempt"],
            },
        },
        "source-banco-export": {
            "sync": {"last_run_at": OLD, "last_status": "ok", "last_event_ref": "memories/system/ingestion/events/event-ingest-banco-2026-05.md"},
            "source_lifecycle": {
                "state": "consolidated", "freshness_state": "stale", "last_attempt_state": "ok",
                "pipeline_stage": "gate_pending", "adoption_state": "pending", "last_sync_success_at": OLD,
                "last_attempt_at": OLD, "emitted_page_ids": ["claim-custos-sobem", "artifact-relatorio-recon"],
                "proposal_ids": ["event-ingest-banco-2026-05"], "raw_artifact_count": 1,
                "secret_safe_log_refs": ["logs/demo/source-banco-export-attempt"],
            },
        },
        "source-agenda": {
            "sync": {"last_run_at": FRESH, "last_status": "ok", "last_event_ref": "memories/system/ingestion/events/event-ingest-agenda-2026-07.md"},
            "source_lifecycle": {
                "state": "ingested", "freshness_state": "fresh", "last_attempt_state": "ok",
                "pipeline_stage": "complete", "adoption_state": "accepted", "accepted_ref": "demo-sha:agenda-accepted",
                "last_sync_success_at": FRESH, "last_ingested_at": FRESH, "last_attempt_at": FRESH,
                "emitted_page_ids": ["meeting-weekly-sync"], "proposal_ids": ["event-ingest-agenda-2026-07"],
                "raw_artifact_count": 1, "secret_safe_log_refs": ["logs/demo/source-agenda-attempt"],
            },
        },
        "source-decision-log": {
            "sync": {"last_run_at": FRESH, "last_status": "ok", "last_event_ref": ""},
            "source_lifecycle": {
                "state": "ingested", "freshness_state": "fresh", "last_attempt_state": "ok",
                "pipeline_stage": "complete", "adoption_state": "reviewed_no_change", "accepted_ref": "demo-sha:decision-log-no-change",
                "last_sync_success_at": FRESH, "last_ingested_at": FRESH, "last_attempt_at": FRESH,
                "reviewed_no_change_receipt": "receipt:demo-decision-log-no-change",
                "secret_safe_log_refs": ["logs/demo/source-decision-log-attempt"],
            },
        },
        "source-health-checks": {
            "relation_cases": [
                {
                    "type": "markdown_link", "target": "source-error-traces", "direction": "directed",
                    "basis": "synthetic_allowed_cycle", "provenance": {"fixture": "failures", "field": "relation_cases"},
                }
            ],
            "sync": {"last_run_at": FRESH, "last_status": "failed", "last_event_ref": ""},
            "source_blocked_reason": "The synthetic health endpoint returned an operational failure.",
            "source_lifecycle": {
                "state": "blocked", "freshness_state": "stale", "last_attempt_state": "failed",
                "pipeline_stage": "manifested", "adoption_state": "pending", "last_attempt_at": FRESH,
                "secret_safe_log_refs": ["logs/demo/source-health-checks-failed"],
            },
        },
        "source-crm-accounts": {
            "region_expectations": {
                "intencao": {
                    "state": "not_applicable",
                    "basis": "This blocked CRM adapter exposes account evidence, not intent records.",
                    "next_interaction": "openDock:source",
                }
            },
            "sync": {"last_run_at": FRESH, "last_status": "needs_auth", "last_event_ref": ""},
            "source_blocked_reason": "Authorization is required; no credential value is stored in the fixture.",
            "source_lifecycle": {
                "state": "blocked", "freshness_state": "never_synced", "last_attempt_state": "needs_auth",
                "pipeline_stage": "configured", "adoption_state": "pending", "last_attempt_at": FRESH,
                "secret_safe_log_refs": ["logs/demo/source-crm-accounts-needs-auth"],
            },
        },
        "source-error-traces": {
            "relation_cases": [
                {
                    "type": "markdown_link", "target": "source-health-checks", "direction": "directed",
                    "basis": "synthetic_allowed_cycle", "provenance": {"fixture": "failures", "field": "relation_cases"},
                },
                {"type": "unknown_demo_relation", "target": "missing-demo-page", "direction": "directed"},
                {"type": "source_ref", "target": "source-health-checks", "direction": "reverse"},
            ],
            "region_expectations": {
                "intencao": {
                    "state": "unknown",
                    "basis": "No template or operator rule has decided whether error traces should project intent.",
                    "next_interaction": "openDock:blocks",
                }
            },
            "sync": {"last_run_at": FRESH, "last_status": "parser_error", "last_event_ref": ""},
            "source_blocked_reason": "The synthetic trace export is malformed.",
            "source_lifecycle": {
                "state": "blocked", "freshness_state": "stale", "last_attempt_state": "parser_error",
                "pipeline_stage": "extracted", "adoption_state": "pending", "last_attempt_at": FRESH,
                "raw_artifact_count": 1, "secret_safe_log_refs": ["logs/demo/source-error-traces-parser"],
            },
        },
        "source-publication-queue": {
            "sync": {"last_run_at": FRESH, "last_status": "secret_blocked", "last_event_ref": ""},
            "source_blocked_reason": "Secret scanning blocked the synthetic attempt before publication.",
            "source_lifecycle": {
                "state": "blocked", "freshness_state": "never_synced", "last_attempt_state": "secret_blocked",
                "pipeline_stage": "extracted", "adoption_state": "pending", "last_attempt_at": FRESH,
                "secret_safe_log_refs": ["logs/demo/source-publication-queue-secret-block"],
            },
        },
    }
    for sid, title, context, platform, moc in sources:
        source_front = fm(
            page_id=sid,
            page_type="source",
            title=title,
            context=context,
            updated_at=FRESH if sid != "source-banco-export" else OLD,
            moc_parent=moc,
            source_type="live",
            platform=platform,
            owner="root-alex-rivera",
        )
        source_front.update(
            lifecycle_fixtures.get(
                sid,
                {
                    "source_lifecycle": {
                        "state": "ready", "freshness_state": "never_synced", "last_attempt_state": "never",
                        "pipeline_stage": "configured", "adoption_state": "pending",
                    }
                },
            )
        )
        pages.append(
            page(
                f"memories/sources/{sid}.md",
                source_front,
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
         ["claim-custos-sobem", "artifact-relatorio-recon"],
         "Normalized import of the bank statement. The claim about cloud costs and the reconciliation report were born here."),
        ("event-ingest-chat-2026-07", "Ingestão: export do chat", FRESH, "source-chat-export", [],
         "Normalized import of the client chat export — the proposal is still awaiting consolidation."),
        ("event-ingest-agenda-2026-07", "Ingestão: agenda", FRESH, "source-agenda", ["meeting-weekly-sync"],
         "Normalized import of the calendar — encounters and cadences refreshed and accepted."),
        ("event-ingest-product-analytics-2026-07", "Ingestão: product analytics", FRESH, "source-product-analytics", ["dashboard-clearpath-activation"],
         "Normalized import of product analytics used by the region-grouping stress demo."),
        ("event-ingest-support-tickets-2026-06", "Ingestão: support tickets", OLD, "source-support-tickets", [],
         "Older helpdesk import kept intentionally overdue and unconsolidated so the demo has stale evidence work."),
    ]
    for eid, title, when, source_ref, consolidated_into, body in ingestion_events:
        event_extra: dict[str, Any] = {}
        if eid == "event-ingest-product-analytics-2026-07":
            event_extra = {
                "proposal_ids": ["proposal-ingest-product-analytics-2026-07"],
                "previous_refs": ["event-ingest-agenda-2026-07"],
            }
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
                    consolidated_into=consolidated_into,
                    **event_extra,
                ),
                f"# {title}\n\n{body}\n\n## Source\n\n- Source: `{source_ref}`\n- Normalized event: this page IS the record of the sync.",
            )
        )

    pages.append(
        page(
            "memories/system/ingestion/proposals/proposal-ingest-product-analytics-2026-07.md",
            fm(
                page_id="proposal-ingest-product-analytics-2026-07",
                page_type="proposal",
                title="Proposal: integrate product analytics evidence",
                context="sistema",
                updated_at=FRESH,
                moc_parent="memories/index.md",
                source_refs=["source-product-analytics"],
                consolidated_into=["dashboard-clearpath-activation"],
                gate_state="approved",
            ),
            "# Proposal: integrate product analytics evidence\n\nSynthetic reviewed proposal connecting the ingest event to the canonical dashboard.",
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
        (
            "action-enviar-proposta",
            "action",
            "Enviar proposta para Caio",
            "clientes",
            "memories/clientes/index.md",
            {
                "status": "open",
                "action_state": "open",
                "owner_kind": "unassigned",
                "created_at": FRESH,
                "next_action": "Send the promised proposal and record the delivery receipt.",
                "priority": "normal",
                "attention_basis": "A promised client follow-up is still open.",
                "source_refs": ["source-agenda"],
                "home_quadrant": "intencao",
            },
            "intencao",
        ),
        ("artifact-dashboard-atlas", "artifact", "Dashboard do Atlas", "clientes", "memories/clientes/product-ops/atlas-launch/index.md", {}, "producao"),
        ("artifact-relatorio-recon", "artifact", "Relatório de reconciliação", "financeiro", "memories/financeiro/index.md", {"source_refs": ["source-banco-export"]}, "producao"),
        # q3 relations/meetings/culture
        ("meeting-weekly-sync", "meeting", "Weekly sync — Product Ops", "clientes", "memories/clientes/product-ops/index.md", {"participants": ["person-joao-mendes"]}, "encontros"),
        ("role-consultora", "role", "Consultora líder", "clientes", "memories/clientes/product-ops/index.md", {}, "pessoas"),
        # q4 systems/process/governance
        ("process-fechamento-mensal", "process", "Fechamento mensal", "financeiro", "memories/financeiro/index.md", {"cadence": "monthly"}, "processos"),
        # Content revalidation: a publication gate is GOVERNANCE (systems).
        ("rule-nada-publica-sem-review", "operational_rule", "Nada publica sem review humano", "sistema", "memories/sistema/index.md", {"home_quadrant": "sistemas"}, "governanca"),
        # Canonical collection index: a real Q1 doorway whose linked scope
        # gathers decisions without rewriting their structural parents.
        (
            "idx-decisoes",
            "ontology_index",
            "Índice de decisões",
            "clientes",
            "memories/clientes/index.md",
            {
                "parent_projection": {
                    "quadrant": "q1",
                    "sub_lens": "intencao",
                    "reason": "The decision index is an intentional collection of choices around the active client world.",
                },
                "collection": {
                    "member_types": ["decision"],
                    "contexts": ["*"],
                },
            },
            None,
        ),
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
        elif lid == "idx-decisoes":
            body += (
                "This canonical index gathers every synthetic decision as a linked collection. "
                "The decisions keep their real structural parents; entering this page changes "
                "the navigation scope, not the underlying hierarchy."
            )
        else:
            body += "Content that lands in its quadrant interior."
        pages.append(page(f"memories/{_leaf_dir(ptype)}/{lid}.md", front, body))

    # --- Region-grouping stress set ---------------------------------------
    # Public synthetic density for the visual-region-grouping plan. These
    # pages make the demo prove dense outputs/evidence, open actions, stale
    # evidence and unsourced conclusions without copying any private wiki data.
    region_stress = [
        ("artifact-region-map-01", "artifact", "Region map sketch 01", "clientes", "memories/clientes/index.md", {"source_refs": ["source-product-analytics"]}, "producao", FRESH),
        ("artifact-region-map-02", "artifact", "Region map sketch 02", "clientes", "memories/clientes/index.md", {"source_refs": ["source-product-analytics"]}, "producao", FRESH),
        ("artifact-region-map-03", "artifact", "Region map sketch 03", "clientes", "memories/clientes/index.md", {"source_refs": ["source-support-tickets"]}, "producao", OLD),
        ("artifact-region-map-04", "artifact", "Region map sketch 04", "clientes", "memories/clientes/product-ops/index.md", {"source_refs": ["source-product-analytics"]}, "producao", FRESH),
        ("artifact-region-map-05", "artifact", "Region map sketch 05", "clientes", "memories/clientes/product-ops/index.md", {"source_refs": ["source-support-tickets"]}, "producao", OLD),
        ("artifact-region-map-06", "artifact", "Region map sketch 06", "clientes", "memories/empresas/clearpath-labs.md", {"source_refs": ["source-clearpath-customer-interviews"]}, "producao", FRESH),
        ("artifact-region-map-07", "artifact", "Region map sketch 07", "clientes", "memories/empresas/clearpath-labs.md", {"source_refs": ["source-product-analytics"]}, "producao", FRESH),
        ("artifact-region-map-08", "artifact", "Region map sketch 08", "clientes", "memories/empresas/clearpath-labs.md", {"source_refs": ["source-support-tickets"]}, "producao", OLD),
        (
            "action-region-review-evidence",
            "action",
            "Review region evidence",
            "clientes",
            "memories/clientes/index.md",
            {
                "status": "open",
                "action_state": "open",
                "owner_kind": "unassigned",
                "created_at": FRESH,
                "next_action": "Review the region evidence and record the result.",
                "priority": "normal",
                "attention_basis": "Dense evidence needs a human review.",
                "source_refs": ["source-product-analytics"],
            },
            "producao",
            FRESH,
        ),
        (
            "action-region-clean-unsourced",
            "action",
            "Clean unsourced region claims",
            "clientes",
            "memories/clientes/index.md",
            {
                "status": "open",
                "action_state": "open",
                "owner_kind": "unassigned",
                "created_at": FRESH,
                "next_action": "Link each unsourced claim or mark it for removal.",
                "priority": "normal",
                "attention_basis": "Unsourced claims weaken evidence quality.",
                "source_refs": ["source-product-analytics"],
            },
            "producao",
            FRESH,
        ),
        (
            "action-region-sync-support",
            "action",
            "Refresh support ticket source",
            "clientes",
            "memories/clientes/index.md",
            {
                "status": "open",
                "action_state": "open",
                "owner_kind": "unassigned",
                "created_at": FRESH,
                "next_action": "Refresh the support-ticket source and verify its receipt.",
                "priority": "high",
                "attention_basis": "The supporting source is outside its freshness window.",
                "source_refs": ["source-support-tickets"],
            },
            "producao",
            OLD,
        ),
        ("claim-region-grouping-needed", "claim", "Dense regions need summaries", "clientes", "memories/clientes/index.md", {}, "percepcao", FRESH),
        ("claim-region-hidden-work", "claim", "Hidden clusters can hide work", "clientes", "memories/clientes/index.md", {}, "percepcao", OLD),
        ("claim-region-evidence-ready", "claim", "Evidence shelf clarifies source-backed work", "clientes", "memories/clientes/product-ops/index.md", {"source_refs": ["source-product-analytics"]}, "percepcao", FRESH),
    ]
    for lid, ptype, title, context, moc, extra, sublens, updated in region_stress:
        front = fm(page_id=lid, page_type=ptype, title=title, context=context, updated_at=updated, moc_parent=moc)
        front.update(extra)
        front["sub_lens"] = sublens
        body = (
            f"# {title}\n\n"
            "Synthetic stress content for the region-grouping cockpit plan. "
            "Its only job is to make dense regions, stale evidence, open actions "
            "and unsourced conclusions visible in the public demo."
        )
        pages.append(page(f"memories/{_leaf_dir(ptype)}/{lid}.md", front, body))

    # Hundreds-scale pressure. These records are deliberately repetitive in
    # shape but not opaque: every ID is stable, every action is canonical, and
    # source/evidence/staleness fields vary deterministically. The normal
    # scenario excludes this prefix; dense_stress includes it and therefore
    # crosses the mobile 350-node threshold while staying below desktop 800.
    for index in range(1, 241):
        page_id = f"artifact-region-pressure-{index:03d}"
        long_label = (
            f"Artefato operacional extremamente detalhado para validar colisão e leitura em português número {index:03d}"
            if index % 12 == 0
            else f"Dense evidence artifact {index:03d}"
        )
        source_refs = ["source-product-analytics" if index % 3 else "source-support-tickets"] if index % 5 else []
        pages.append(
            page(
                f"memories/artifacts/{page_id}.md",
                fm(
                    page_id=page_id,
                    page_type="artifact",
                    title=long_label,
                    context="clientes",
                    updated_at=OLD if index % 7 == 0 else FRESH,
                    moc_parent="memories/clientes/index.md" if index % 2 else "memories/clientes/product-ops/index.md",
                    sub_lens="producao",
                    source_refs=source_refs,
                ),
                f"# {long_label}\n\nPublic deterministic density artifact {index:03d}; source links and freshness are real fixture fields.",
            )
        )

    action_states = ("open", "in_progress", "blocked", "waiting_human", "done", "cancelled")
    owner_kinds = ("human", "agent", "system", "other", "unassigned")
    for index in range(1, 61):
        page_id = f"action-region-pressure-{index:03d}"
        state = action_states[(index - 1) % len(action_states)]
        owner_kind = owner_kinds[(index - 1) % len(owner_kinds)]
        owner_ref = "" if owner_kind == "unassigned" else (
            "person-marina-costa" if owner_kind == "human" else f"demo-{owner_kind}-operator"
        )
        title = (
            f"Ação que aguarda julgamento humano sobre evidência sintética de alta densidade {index:03d}"
            if state == "waiting_human"
            else f"Dense canonical action {index:03d}"
        )
        due_at = "2026-06-15" if index % 4 == 0 else "2026-08-15"
        extra: dict[str, Any] = {
            "action_state": state,
            "owner_kind": owner_kind,
            "owner_ref": owner_ref,
            "created_at": "2026-06-01",
            "due_at": due_at,
            "parent_ref": "hub-clientes",
            "source_refs": ["source-support-tickets"],
            "evidence_refs": [
                "dashboard-clearpath-activation"
                if index == 1
                else f"artifact-region-pressure-{((index - 1) % 240) + 1:03d}"
            ],
            "next_action": "Review the linked synthetic evidence and leave a human-gated receipt.",
            "priority": "high" if index % 3 == 0 else "normal",
            "attention_basis": (
                "The synthetic action is overdue."
                if due_at < FRESH
                else "Its lifecycle and evidence state require review."
            ),
        }
        if state == "blocked":
            extra.update({"blocked_by": ["source-support-tickets"], "blocker_reason": "Synthetic parser dependency is blocked."})
        if state == "done":
            extra.update({"completed_at": FRESH, "completion_receipt": f"receipt:demo-action-done-{index:03d}"})
        if state == "cancelled":
            extra["cancellation_receipt"] = f"receipt:demo-action-cancelled-{index:03d}"
        pages.append(
            page(
                f"memories/actions/{page_id}.md",
                fm(
                    page_id=page_id,
                    page_type="action",
                    title=title,
                    context="clientes",
                    updated_at=OLD if index % 4 == 0 else FRESH,
                    stale_after_days=30,
                    moc_parent="memories/clientes/index.md",
                    sub_lens="intencao" if state in {"open", "waiting_human", "blocked"} else "producao",
                    **extra,
                ),
                f"# {title}\n\nCanonical synthetic work object {index:03d}; it is not an executable operator command.",
            )
        )

    for index in range(1, 61):
        page_id = f"claim-region-pressure-{index:03d}"
        title = (
            f"Conclusão sintética sem evidência precisa permanecer visível e explicável {index:03d}"
            if index % 10 == 0
            else f"Dense evidence claim {index:03d}"
        )
        pages.append(
            page(
                f"memories/claims/{page_id}.md",
                fm(
                    page_id=page_id,
                    page_type="claim",
                    title=title,
                    context="clientes",
                    updated_at=OLD if index % 6 == 0 else FRESH,
                    moc_parent="memories/clientes/index.md",
                    sub_lens="percepcao",
                    source_refs=["source-product-analytics"] if index % 4 else [],
                ),
                f"# {title}\n\nPublic deterministic claim {index:03d}; missing evidence is intentional when source_refs is empty.",
            )
        )

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


def write_fixture(
    target: Path,
    stage: int = FINAL_STAGE,
    *,
    scenario_id: str | None = None,
) -> list[str]:
    """Write one fixture universe into ``target`` and return its page IDs.

    With no ``scenario_id`` this writes the complete authored cast. Scenario
    snapshots filter that cast through the executable scenario manifest before
    applying the Genesis stage boundary. Keeping those two concerns separate
    lets the repository retain every synthetic fixture while the default demo
    remains calm and instructional.
    """
    memories = target / "memories"
    if memories.exists():
        shutil.rmtree(memories)
    selected = (
        set(scenario_page_ids(scenario_id)) if scenario_id is not None else None
    )
    written: list[str] = []
    for rel, front, body in build_pages():
        page_id = str(front.get("page_id") or "")
        if selected is not None and page_id not in selected:
            continue
        if _stage_of(front) > stage:
            continue
        if page_id == "root-alex-rivera":
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


def _input_files(fixture_root: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for path in sorted(item for item in fixture_root.rglob("*") if item.is_file()):
        rel = path.relative_to(fixture_root).as_posix()
        if rel.startswith("scenarios/"):
            continue
        entries.append((f"fixture/{rel}", path.read_bytes()))
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        entries.append((f"scenarios/{path.name}", path.read_bytes()))
    return entries


def source_input_hash(fixture_root: Path) -> str:
    """Hash authored scenario manifests plus the exact generated wiki inputs."""
    digest = hashlib.sha256()
    for rel, content in _input_files(fixture_root):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _fixture_metadata(
    fixture_root: Path,
    *,
    stage: int | None = None,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    resolved_scenario = (
        "walking_skeleton"
        if stage is not None
        else scenario_id or DEFAULT_DEMO_SCENARIO
    )
    scenario = load_scenario_manifests()[resolved_scenario]
    return {
        "fixture_id": DEMO_FIXTURE_ID,
        "scenario_id": resolved_scenario,
        "scenario_ids": list(REQUIRED_SCENARIOS),
        "seed": int(scenario["seed"]),
        "source_input_sha256": source_input_hash(fixture_root),
        "reference_date": DEMO_REFERENCE_DATE.isoformat(),
        **({"genesis_stage": stage} if stage is not None else {}),
    }


def _write_snapshot_deterministic(
    fixture_root: Path,
    out_dir: Path,
    *,
    stage: int | None = None,
    scenario_id: str | None = None,
) -> dict[str, Path]:
    """Build one frozen snapshot from a self-contained temporary fixture."""
    from wiki_core.config import load_config
    from wiki_core.web import snapshot as snapshot_module
    from wiki_core.web.sources import build_sources_payload

    config = load_config(fixture_root)
    original_today = snapshot_module._today
    original_sources = snapshot_module._safe_source_entities

    def frozen_sources(root: Path, loaded_config: Any) -> dict[str, Any]:
        try:
            return build_sources_payload(root, loaded_config, today=DEMO_REFERENCE_DATE)
        except Exception as exc:  # noqa: BLE001 - same safe snapshot contract
            return {"schema_version": "wiki_web_source_entities.v1", "sources": [], "error": str(exc)}

    snapshot_module._today = lambda: DEMO_REFERENCE_DATE
    snapshot_module._safe_source_entities = frozen_sources
    try:
        payloads = snapshot_module.build_snapshot(
            fixture_root,
            config,
            mode="static",
            generated_at=DEMO_GENERATED_AT,
            content_sidecars=True,
        )
    finally:
        snapshot_module._today = original_today
        snapshot_module._safe_source_entities = original_sources

    payloads["manifest.json"]["fixture"] = _fixture_metadata(
        fixture_root, stage=stage, scenario_id=scenario_id
    )
    artifacts = snapshot_module.prepare_snapshot_artifacts(
        fixture_root, config, payloads, content_sidecars=True
    )
    return snapshot_module.promote_snapshot_artifacts(out_dir, artifacts)


def build_stage_snapshots(out_root: Path | None = None) -> dict[str, Any]:
    """Build one real, deterministic snapshot per genesis stage."""
    out_root = out_root or OUT
    stages_dir = out_root / "stages"
    if stages_dir.exists():
        shutil.rmtree(stages_dir)
    manifest: dict[str, Any] = {
        "schema_version": "wiki_genesis_stages.v1",
        "fixture_id": DEMO_FIXTURE_ID,
        "scenario_id": "walking_skeleton",
        "seed": DEMO_SEED,
        "final_stage": FINAL_STAGE,
        "stages": [],
    }
    previous: set[str] = set()
    for stage in range(FINAL_STAGE + 1):
        with tempfile.TemporaryDirectory(prefix=f"wiki-demo-stage-{stage}-") as tmp:
            tmp_root = Path(tmp)
            page_ids = set(
                write_fixture(
                    tmp_root,
                    stage,
                    scenario_id=DEFAULT_DEMO_SCENARIO,
                )
            )
            out_dir = stages_dir / str(stage)
            _write_snapshot_deterministic(tmp_root, out_dir, stage=stage)
            manifest["stages"].append(
                {
                    "stage": stage,
                    "dir": f"stages/{stage}",
                    "focus": STAGE_FOCUS.get(stage, ""),
                    "page_count": len(page_ids),
                    "page_id_sha256": page_id_hash(sorted(page_ids)),
                    "source_input_sha256": source_input_hash(tmp_root),
                    "added_pages": sorted(page_ids - previous),
                    "root_attachments": root_attachments(stage) if stage >= 1 else {},
                }
            )
            previous = page_ids
    stages_dir.mkdir(parents=True, exist_ok=True)
    (stages_dir / "stages.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _build_scenario_snapshot(scenario_id: str, out_dir: Path) -> dict[str, Any]:
    """Build one manifest-selected scenario into an isolated snapshot tree."""
    with tempfile.TemporaryDirectory(prefix=f"wiki-demo-{scenario_id}-") as tmp:
        fixture_root = Path(tmp)
        page_ids = write_fixture(
            fixture_root,
            FINAL_STAGE,
            scenario_id=scenario_id,
        )
        written = _write_snapshot_deterministic(
            fixture_root,
            out_dir,
            scenario_id=scenario_id,
        )
        return {
            "scenario_id": scenario_id,
            "page_count": len(page_ids),
            "snapshot_file_count": len(written),
            "source_input_sha256": source_input_hash(fixture_root),
        }


def build_demo(fixture_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Generate the complete authored fixture and scenario snapshots."""
    authored_page_ids = write_fixture(fixture_dir, FINAL_STAGE)
    default = _build_scenario_snapshot(DEFAULT_DEMO_SCENARIO, out_dir)
    stages = build_stage_snapshots(out_dir)
    scenarios: dict[str, dict[str, Any]] = {}
    for scenario_id in EXPLICIT_SNAPSHOT_SCENARIOS:
        scenarios[scenario_id] = _build_scenario_snapshot(
            scenario_id,
            out_dir / "scenarios" / scenario_id,
        )
    return {
        "page_count": len(authored_page_ids),
        "default_page_count": default["page_count"],
        "snapshot_file_count": default["snapshot_file_count"],
        "stage_count": len(stages["stages"]),
        "source_input_sha256": source_input_hash(fixture_dir),
        "scenario_snapshots": scenarios,
    }


def _fixture_file_map(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    memories = root / "memories"
    if memories.exists():
        for path in sorted(item for item in memories.rglob("*") if item.is_file()):
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    for name in GENERATED_FIXTURE_CONFIGS:
        path = root / name
        if path.is_file():
            files[name] = path.read_bytes()
    return files


def _tree_file_map(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _map_drift(generated: dict[str, bytes], committed: dict[str, bytes], label: str) -> list[str]:
    drift: list[str] = []
    for rel in sorted(generated.keys() - committed.keys()):
        drift.append(f"{label}: missing {rel}")
    for rel in sorted(committed.keys() - generated.keys()):
        drift.append(f"{label}: unexpected {rel}")
    for rel in sorted(generated.keys() & committed.keys()):
        if generated[rel] != committed[rel]:
            drift.append(f"{label}: changed {rel}")
    return drift


def demo_drift(fixture_dir: Path | None = None, out_dir: Path | None = None) -> list[str]:
    """Regenerate in an isolated directory and report committed-artifact drift."""
    fixture_dir = fixture_dir or FIXTURE
    out_dir = out_dir or OUT
    with tempfile.TemporaryDirectory(prefix="wiki-demo-check-") as tmp:
        generated_fixture = Path(tmp) / "fixture"
        generated_out = Path(tmp) / "snapshot"
        build_demo(generated_fixture, generated_out)
        return [
            *_map_drift(_fixture_file_map(generated_fixture), _fixture_file_map(fixture_dir), "fixture"),
            *_map_drift(_tree_file_map(generated_out), _tree_file_map(out_dir), "snapshot"),
        ]


def _replace_generated_fixture(generated: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    memories = target / "memories"
    if memories.exists():
        shutil.rmtree(memories)
    shutil.copytree(generated / "memories", memories)
    for name in GENERATED_FIXTURE_CONFIGS:
        shutil.copy2(generated / name, target / name)


def _replace_tree(generated: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(generated, target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify the deterministic public Wiki Viva demo")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in a temporary directory and fail if committed fixture/snapshot artifacts drift",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Loading the registry is a gate in both modes: malformed or incomplete
    # scenario contracts must never produce apparently valid snapshots.
    validate_scenario_manifests()
    if args.check:
        drift = demo_drift()
        if drift:
            print(f"demo drift: {len(drift)} generated artifact(s) differ", file=sys.stderr)
            for item in drift[:40]:
                print(f"  - {item}", file=sys.stderr)
            if len(drift) > 40:
                print(f"  - ... and {len(drift) - 40} more", file=sys.stderr)
            print("run scripts/wiki_build_demo.py to regenerate intentionally", file=sys.stderr)
            return 1
        print(f"demo: deterministic fixture and snapshot are current ({DEMO_FIXTURE_ID}, seed {DEMO_SEED})")
        return 0

    with tempfile.TemporaryDirectory(prefix="wiki-demo-build-") as tmp:
        generated_fixture = Path(tmp) / "fixture"
        generated_out = Path(tmp) / "snapshot"
        report = build_demo(generated_fixture, generated_out)
        _replace_generated_fixture(generated_fixture, FIXTURE)
        _replace_tree(generated_out, OUT)
    print(
        f"demo: {report['default_page_count']} instructional pages "
        f"({report['page_count']} authored) -> {report['snapshot_file_count']} snapshot files "
        f"in {OUT.relative_to(KIT_ROOT)} + {report['stage_count']} genesis stages "
        f"+ {len(report['scenario_snapshots'])} explicit scenario snapshot(s) "
        f"(input {report['source_input_sha256'][:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
