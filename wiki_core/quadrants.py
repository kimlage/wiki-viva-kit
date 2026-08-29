"""Canonical Wilber/AQAL quadrant contract for wiki consumers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuadrantDefinition:
    quadrant_id: str
    semantic_key: str
    label_en: str
    label_es: str
    label_pt: str
    aqal_position_en: str
    aqal_position_es: str
    aqal_position_pt: str
    perspective_id: str
    operational_test_en: str
    operational_test_es: str
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
        label_es="Q1 - Identidad e intención",
        label_pt="Q1 - Identidade e intencao",
        aqal_position_en="I / interior individual / upper-left",
        aqal_position_es="Yo / interior individual / superior izquierdo",
        aqal_position_pt="Eu / interior individual / superior esquerdo",
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
        operational_test_es=(
            "Vista interior del holón raíz: identidad, intención, significado, "
            "prioridades o límites vividos o declarados. Para un equipo, empresa "
            "o producto, no invente conciencia; use la misión declarada, la "
            "autodescripción o la intención de las partes interesadas."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q2",
        semantic_key="exterior_individual",
        label_en="Q2 - Outputs and evidence",
        label_es="Q2 - Resultados y evidencias",
        label_pt="Q2 - Saidas e evidencias",
        aqal_position_en="It / exterior individual / upper-right",
        aqal_position_es="Eso / exterior individual / superior derecho",
        aqal_position_pt="Isso / exterior individual / superior direito",
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
        operational_test_es=(
            "Vista exterior del holón raíz como una entidad: comportamiento "
            "observable, resultado directo, artefacto propio, evidencia o métrica. "
            "Que algo sea un documento o repositorio no basta; debe ser un "
            "resultado o evidencia de la entidad raíz."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q3",
        semantic_key="interior_collective",
        label_en="Q3 - Culture and relations",
        label_es="Q3 - Cultura y relaciones",
        label_pt="Q3 - Cultura e relacoes",
        aqal_position_en="We / interior collective / lower-left",
        aqal_position_es="Nosotros / interior colectivo / inferior izquierdo",
        aqal_position_pt="Nos / interior coletivo / inferior esquerdo",
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
        operational_test_es=(
            "Vista interior del colectivo: significado compartido, cultura, roles "
            "como expectativas vividas, relaciones, rituales y normas. Una lista "
            "de personas o un organigrama formal no es Q3 salvo que represente el "
            "significado compartido o el campo relacional."
        ),
    ),
    QuadrantDefinition(
        quadrant_id="q4",
        semantic_key="exterior_collective",
        label_en="Q4 - Systems and governance",
        label_es="Q4 - Sistemas y gobernanza",
        label_pt="Q4 - Sistemas e governanca",
        aqal_position_en="Its / exterior collective / lower-right",
        aqal_position_es="Esos / exterior colectivo / inferior derecho",
        aqal_position_pt="Esses / exterior coletivo / inferior direito",
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
        operational_test_es=(
            "Vista exterior del colectivo: sistemas, canales, herramientas, "
            "plataformas, flujos de trabajo, reglas, instituciones, gobernanza e "
            "infraestructura de procesos."
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

BOUNDARY_RULE_ES = (
    "Aplique el cuadrante al holón raíz y al papel de la fuente en el contexto. "
    "Un repositorio, documento, panel o ticket es Q2 solo cuando constituye un "
    "artefacto, resultado o evidencia propios de la entidad raíz. La plataforma, "
    "el flujo de trabajo, la regla de gobernanza o el canal de comunicación que "
    "coordina a las personas a su alrededor es Q4. Las personas, los roles y las "
    "relaciones son Q3 solo cuando se leen como significado compartido, expectativa "
    "mutua o cultura; como estructura administrada externamente pertenecen a Q4."
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

ANTI_PATTERNS_ES = (
    "Q2 = cualquier archivo, repositorio, documento o herramienta",
    "Q3 = cualquier persona, lista de roles, registro, organigrama o RACI",
    "Q4 = todo artefacto solo porque reside dentro de un sistema",
)


def is_portuguese(language: str) -> bool:
    return language.lower().startswith("pt")


def is_spanish(language: str) -> bool:
    return language.lower().startswith("es")


def quadrant_semantics(language: str = "en") -> dict[str, dict[str, str]]:
    portuguese = is_portuguese(language)
    spanish = is_spanish(language)
    return {
        quadrant.quadrant_id: {
            "semantic_key": quadrant.semantic_key,
            "label": quadrant.label_pt if portuguese else quadrant.label_es if spanish else quadrant.label_en,
            "aqal_position": (
                quadrant.aqal_position_pt
                if portuguese
                else quadrant.aqal_position_es
                if spanish
                else quadrant.aqal_position_en
            ),
            "operational_test": (
                quadrant.operational_test_pt
                if portuguese
                else quadrant.operational_test_es
                if spanish
                else quadrant.operational_test_en
            ),
        }
        for quadrant in QUADRANTS
    }


def quadrant_boundary_rule(language: str = "en") -> str:
    if is_portuguese(language):
        return BOUNDARY_RULE_PT
    if is_spanish(language):
        return BOUNDARY_RULE_ES
    return BOUNDARY_RULE_EN


def quadrant_contract(language: str = "en") -> dict[str, object]:
    portuguese = is_portuguese(language)
    spanish = is_spanish(language)
    semantics = quadrant_semantics(language)
    if portuguese:
        model = "Quatro quadrantes de Wilber/AQAL"
        axes = {"interior_exterior": "interior/exterior", "individual_collective": "individual/coletivo"}
        anti_patterns = ANTI_PATTERNS_PT
    elif spanish:
        model = "Cuatro cuadrantes de Wilber/AQAL"
        axes = {"interior_exterior": "interior/exterior", "individual_collective": "individual/colectivo"}
        anti_patterns = ANTI_PATTERNS_ES
    else:
        model = "Wilber/AQAL four quadrants"
        axes = {"interior_exterior": "interior/exterior", "individual_collective": "individual/collective"}
        anti_patterns = ANTI_PATTERNS_EN
    return {
        "schema_version": "wiki_quadrant_contract.v1",
        "model": model,
        "axis_pair": axes,
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
        "anti_patterns": list(anti_patterns),
    }
