from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wiki_core.config import load_config
from wiki_core.quadrants import quadrant_contract


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT)
REFERENCES_ROOT = ROOT / CONFIG.paths["references_root"]
MEMORY_ROOT = ROOT / CONFIG.paths["memory_root"]


def test_context_deep_read_prompt_preserves_aqal_boundaries() -> None:
    prompt = (ROOT / "wiki_core/llm/prompts/context_deep_read.v3.md").read_text(
        encoding="utf-8"
    )
    normalized_prompt = " ".join(prompt.split())

    assert "interior/exterior" in prompt
    assert "individual/collective" in prompt
    assert "`interior_individual` | `I`, interior individual, upper-left" in prompt
    assert "`exterior_individual` | `It`, exterior individual, upper-right" in prompt
    assert "`interior_collective` | `We`, interior collective, lower-left" in prompt
    assert "`exterior_collective` | `Its`, exterior collective, lower-right" in prompt
    assert "A plain roster, org chart, RACI or workflow assignment" in normalized_prompt
    assert "administered structure as `exterior_collective`" in normalized_prompt


def test_public_quadrant_report_rejects_lossy_entity_bucket_mapping() -> None:
    if CONFIG.language == "pt":
        report = (REFERENCES_ROOT / "reports/alinhamento-quadrantes-aqal-2026-06-25.md").read_text(encoding="utf-8")
        assert "Q3 nao e cadastro de pessoas" in report
        assert "Q2 nao e todo arquivo" in report
        assert "Classificar o fato extraido" in report
        assert "Pessoa/papel" in report
        assert "organograma, RACI, regra de aprovacao ou atribuicao de workflow" in report
    else:
        report = (REFERENCES_ROOT / "reports/aqal-quadrant-alignment-2026-06-25.md").read_text(encoding="utf-8")
        assert "The current kit does not support the interpretation" in report
        assert "Q3 = any people/roles" in report
        assert "Q2 = any file/repository" in report
        assert "classify the extracted fact in relation to the root holon" in report


def test_methodology_references_do_not_teach_q3_as_plain_people_bucket() -> None:
    if CONFIG.language == "pt":
        root = (MEMORY_ROOT / "index.md").read_text(encoding="utf-8")
        registry = (MEMORY_ROOT / "sistema/perspectivas/index.md").read_text(encoding="utf-8")
        assert "Pessoas entram como participantes de relacoes, nao como cadastro plano" in root
        assert "papeis-como-administrados" in registry
        assert "nao e o contrato AQAL de Q3" in registry
        return
    proposal = (
        REFERENCES_ROOT
        / "proposals/integral-root-entity-and-input-stage-refactor-2026-06-25.md"
    ).read_text(encoding="utf-8")
    channel = (MEMORY_ROOT / "system/input-channels/methodology-reference.md").read_text(
        encoding="utf-8"
    )

    assert 'Q3["Q3 - roles, people, culture and relationships"]' not in proposal
    assert 'Q3 --> People["People, roles, responsibilities"]' not in proposal
    assert "| Q1/Q2/Q3/Q4 | identity, artifacts, roles, systems |" not in channel
    assert "shared meaning/roles-as-lived" in channel


def test_root_overlays_preserve_aqal_boundary_when_read_without_base_template() -> None:
    if CONFIG.language == "pt":
        root_template = (REFERENCES_ROOT / "templates/wiki/root-entity.md").read_text(encoding="utf-8")
        assert "Pessoas entram como participantes de um campo social, nao como cadastro plano" in root_template
        assert "plataforma, workflow, regra de governanca ou canal" in root_template
        assert "estrutura administrada externamente pertencem a Q4" in root_template
        return
    person = (REFERENCES_ROOT / "templates/wiki/root-person.md").read_text(
        encoding="utf-8"
    )
    team = (REFERENCES_ROOT / "templates/wiki/root-team.md").read_text(
        encoding="utf-8"
    )
    company = (REFERENCES_ROOT / "templates/wiki/root-company.md").read_text(
        encoding="utf-8"
    )

    assert "Social contexts are Q3 only" in person
    assert (
        "Communication channels such as email, calendar, Drive and chat are Q4"
        in person
    )
    assert (
        "Team membership, org charts, RACI rows and workflow assignments are not Q3"
        in team
    )
    assert "Repositories, tools and boards are Q2 only" in team
    assert (
        "Units, departments, governance forums and reporting lines are not Q3"
        in company
    )
    assert (
        "Systems of record, CRM/ERP, document systems, support systems, calendars"
        in company
    )


def test_topical_stakeholder_perspective_does_not_define_q3() -> None:
    if CONFIG.language == "pt":
        registry = (MEMORY_ROOT / "sistema/perspectivas/index.md").read_text(encoding="utf-8")
        stakeholder = (MEMORY_ROOT / "sistema/perspectivas/pessoas.md").read_text(encoding="utf-8")
        roles = (MEMORY_ROOT / "sistema/perspectivas/papeis-relacoes.md").read_text(encoding="utf-8")
        assert "lentes tematicas" in registry
        assert "nao e o contrato AQAL de Q3" in registry
        assert "nao o contrato de quadrante Q3" in " ".join(stakeholder.split())
        assert "permanecem Q4" in stakeholder
        assert "Uma lista plana de pessoas nao basta para Q3" in roles
        assert "estrutura administrada, RACI, regra de aprovacao ou workflow" in roles
        return
    registry = (MEMORY_ROOT / "system/perspectives/index.md").read_text(
        encoding="utf-8"
    )
    stakeholder = (MEMORY_ROOT / "system/perspectives/stakeholder.md").read_text(
        encoding="utf-8"
    )
    roles = (MEMORY_ROOT / "system/perspectives/roles-relationships.md").read_text(
        encoding="utf-8"
    )

    assert "topical perspectives" in registry
    assert "not the Q3 AQAL contract" in registry
    assert "This is a topical stakeholder perspective, not the Q3 quadrant contract" in stakeholder
    assert "assignments as Q4 unless" in stakeholder
    assert "quadrant: q3" in roles


def test_quadrant_contract_is_authoritative_for_external_consumers() -> None:
    contract = quadrant_contract("en")
    quadrants = contract["quadrants"]

    assert contract["schema_version"] == "wiki_quadrant_contract.v1"
    assert contract["axis_pair"] == {
        "interior_exterior": "interior/exterior",
        "individual_collective": "individual/collective",
    }
    assert quadrants["q1"]["semantic_key"] == "interior_individual"
    assert quadrants["q1"]["label"] == "Q1 - Identity and intent"
    assert quadrants["q1"]["aqal_position"] == "I / interior individual / upper-left"
    assert quadrants["q2"]["semantic_key"] == "exterior_individual"
    assert quadrants["q2"]["label"] == "Q2 - Outputs and evidence"
    assert quadrants["q2"]["aqal_position"] == "It / exterior individual / upper-right"
    assert quadrants["q3"]["semantic_key"] == "interior_collective"
    assert quadrants["q3"]["label"] == "Q3 - Culture and relations"
    assert quadrants["q3"]["aqal_position"] == "We / interior collective / lower-left"
    assert quadrants["q4"]["semantic_key"] == "exterior_collective"
    assert quadrants["q4"]["label"] == "Q4 - Systems and governance"
    assert quadrants["q4"]["aqal_position"] == "Its / exterior collective / lower-right"
    assert quadrants["q3"]["perspective_id"] == "perspective-roles-relationships"
    assert "plain people roster" in quadrants["q3"]["operational_test"]
    assert "output/evidence of the root entity" in quadrants["q2"]["operational_test"]
    assert "q2 only" in contract["boundary_rule"]
    assert "they belong to q4" in contract["boundary_rule"]
    assert "Q3 = any person, role list, roster, org chart or RACI" in contract["anti_patterns"]


def test_quadrant_contract_cli_matches_python_contract() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_quadrant_contract.py"),
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == quadrant_contract(CONFIG.language)
