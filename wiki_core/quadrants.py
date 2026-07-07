"""Canonical Wilber/AQAL quadrant contract for wiki consumers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuadrantDefinition:
    quadrant_id: str
    semantic_key: str
    label_en: str
    label_pt: str
    aqal_position: str
    perspective_id: str
    operational_test_en: str
    operational_test_pt: str


DEFAULT_QUADRANT_MAP = {
    "q1": ["perspective-identity-intent"],
    "q2": ["perspective-artifacts-evidence"],
    "q3": ["perspective-roles-relationships"],
    "q4": ["perspective-systems-processes"],
}

QUADRANTS: tuple[QuadrantDefinition, ...] = (
    QuadrantDefinition(
        quadrant_id="q1",
        semantic_key="interior_individual",
        label_en="Q1 - Identity and intent",
        label_pt="Q1 - Identidade e intencao",
        aqal_position="I / interior individual / upper-left",
        perspective_id="perspective-identity-intent",
        operational_test_en=(
            "Interior view of the root holon: lived or declared identity, intent, "
            "meaning, priorities or constraints. For a team/company/product, do "
            "not invent consciousness; use stated mission, self-description or "
            "stakeholder intent."
        ),
        operational_test_pt=(
            "Vista interior do holon raiz: identidade, intencao, significado, "
            "prioridades ou limites vividos ou declarados. Para time, empresa "
            "ou produto, nao inventar consciencia; usar missao declarada, "
            "autodescricao ou intencao de stakeholders."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q2",
        semantic_key="exterior_individual",
        label_en="Q2 - Outputs and evidence",
        label_pt="Q2 - Saidas e evidencias",
        aqal_position="It / exterior individual / upper-right",
        perspective_id="perspective-artifacts-evidence",
        operational_test_en=(
            "Exterior view of the root holon as one entity: observable behavior, "
            "direct output, owned artifact, evidence or metric. The fact that "
            "something is a document or repository is not enough; it must be an "
            "output/evidence of the root entity."
        ),
        operational_test_pt=(
            "Vista exterior do holon raiz como uma entidade: comportamento "
            "observavel, output direto, artefato proprio, evidencia ou metrica. "
            "O fato de algo ser documento ou repositorio nao basta; precisa ser "
            "output/evidencia da entidade raiz."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q3",
        semantic_key="interior_collective",
        label_en="Q3 - Culture and relations",
        label_pt="Q3 - Cultura e relacoes",
        aqal_position="We / interior collective / lower-left",
        perspective_id="perspective-roles-relationships",
        operational_test_en=(
            "Interior view of the collective: shared meaning, culture, roles as "
            "lived expectations, relationships, rituals and norms. A plain people "
            "roster or formal org chart is not Q3 unless it carries the shared "
            "meaning or relationship field."
        ),
        operational_test_pt=(
            "Vista interior do coletivo: significado compartilhado, cultura, "
            "papeis como expectativas vividas, relacoes, rituais e normas. Um "
            "cadastro simples de pessoas ou organograma formal nao e Q3 salvo "
            "quando carrega significado compartilhado ou campo relacional."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q4",
        semantic_key="exterior_collective",
        label_en="Q4 - Systems and governance",
        label_pt="Q4 - Sistemas e governanca",
        aqal_position="Its / exterior collective / lower-right",
        perspective_id="perspective-systems-processes",
        operational_test_en=(
            "Exterior view of the collective: systems, channels, tools, platforms, "
            "workflows, rules, institutions, governance and process infrastructure."
        ),
        operational_test_pt=(
            "Vista exterior do coletivo: sistemas, canais, ferramentas, "
            "plataformas, workflows, regras, instituicoes, governanca e "
            "infraestrutura de processo."
        ),
    ),
)

BOUNDARY_RULE_EN = (
    "Apply the quadrant to the root holon and the source's role in context. A "
    "repository, document, dashboard or ticket is q2 only when it is an owned "
    "artifact/output/evidence of the root entity. The platform, workflow, "
    "governance rule or communication channel that coordinates people around it "
    "is q4. People, roles and relationships are q3 only when read as shared "
    "meaning, mutual expectation or culture; as externally administered structure "
    "they belong to q4."
)

BOUNDARY_RULE_PT = (
    "Aplicar o quadrante ao holon raiz e ao papel da fonte no contexto. Um "
    "repositorio, documento, dashboard ou ticket e q2 apenas quando e um "
    "artefato/output/evidencia proprio da entidade raiz. A plataforma, workflow, "
    "regra de governanca ou canal de comunicacao que coordena pessoas ao redor "
    "dele e q4. Pessoas, papeis e relacoes sao q3 apenas quando lidas como "
    "significado compartilhado, expectativa mutua ou cultura; como estrutura "
    "administrada externamente, pertencem a q4."
)

ANTI_PATTERNS_EN = (
    "Q2 = any file, repository, document or tool",
    "Q3 = any person, role list, roster, org chart or RACI",
    "Q4 = every artifact just because it lives inside a system",
)

ANTI_PATTERNS_PT = (
    "Q2 = qualquer arquivo, repositorio, documento ou ferramenta",
    "Q3 = qualquer pessoa, lista de papeis, cadastro, organograma ou RACI",
    "Q4 = todo artefato apenas porque vive dentro de um sistema",
)


def is_portuguese(language: str) -> bool:
    return language.lower().startswith("pt")


def quadrant_semantics(language: str = "en") -> dict[str, dict[str, str]]:
    portuguese = is_portuguese(language)
    return {
        quadrant.quadrant_id: {
            "semantic_key": quadrant.semantic_key,
            "label": quadrant.label_pt if portuguese else quadrant.label_en,
            "aqal_position": quadrant.aqal_position,
            "operational_test": (
                quadrant.operational_test_pt if portuguese else quadrant.operational_test_en
            ),
        }
        for quadrant in QUADRANTS
    }


def quadrant_boundary_rule(language: str = "en") -> str:
    return BOUNDARY_RULE_PT if is_portuguese(language) else BOUNDARY_RULE_EN


def quadrant_contract(language: str = "en") -> dict[str, object]:
    portuguese = is_portuguese(language)
    semantics = quadrant_semantics(language)
    return {
        "schema_version": "wiki_quadrant_contract.v1",
        "model": "Wilber/AQAL four quadrants",
        "axis_pair": {
            "interior_exterior": "interior/exterior",
            "individual_collective": "individual/collective",
        },
        "quadrants": {
            quadrant.quadrant_id: {
                **semantics[quadrant.quadrant_id],
                "perspective_id": quadrant.perspective_id,
            }
            for quadrant in QUADRANTS
        },
        "perspective_map": {
            quadrant_id: list(perspectives)
            for quadrant_id, perspectives in DEFAULT_QUADRANT_MAP.items()
        },
        "boundary_rule": quadrant_boundary_rule(language),
        "anti_patterns": list(ANTI_PATTERNS_PT if portuguese else ANTI_PATTERNS_EN),
    }
