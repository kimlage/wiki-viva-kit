export type PrototypeVariantId = "organism" | "table" | "scales";
export type RendererMode = "3d" | "2d";
export type LensId = "hydrology" | "climate" | "compare";
export type MissionChoice = "do" | "delegate" | "ask_evidence" | "compost";
export type ClaimDecision = "accept" | "correct" | "reject";
export type ClaimId = "east_watered" | "east_recovering" | "whole_garden_resolved";

export type PrototypePhase =
  | "quiet"
  | "diff_available"
  | "tension_focused"
  | "mission_selected"
  | "offscreen_action"
  | "evidence_returned"
  | "agent_proposal"
  | "human_gate"
  | "receipt_issued"
  | "mutation_committed"
  | "session_closed";

export type PrototypeVariant = {
  id: PrototypeVariantId;
  key: "A" | "B" | "C";
  name: string;
  shortName: string;
  promise: string;
};

export const PROTOTYPE_VARIANTS: readonly PrototypeVariant[] = [
  {
    id: "organism",
    key: "A",
    name: "Organismo persistente",
    shortName: "Organismo",
    promise: "O mundo permanece presente enquanto a precisão 2D nasce do lugar selecionado."
  },
  {
    id: "table",
    key: "B",
    name: "Mesa topográfica",
    shortName: "Mesa",
    promise: "Contexto e precisão vivem no mesmo artefato cartográfico de câmera contida."
  },
  {
    id: "scales",
    key: "C",
    name: "Escalas diretas",
    shortName: "Escalas",
    promise: "Mundo, distrito e interior dividem responsabilidades sem perder o mesmo ID."
  }
] as const;

export const ANATTA_FIXTURE = {
  world: {
    id: "world.aurora-garden",
    name: "Jardim Aurora",
    intentionId: "intention.responsible-care",
    intention: "Manter a horta saudável, com uso responsável de água e decisões rastreáveis."
  },
  source: {
    id: "source.aurora-station",
    name: "Estação Comunitária Aurora",
    owner: "Coletivo Aurora · fixture sintética",
    policy: "read-only",
    freshness: "observação diária"
  },
  snapshots: {
    day0: {
      id: "snapshot.day-0",
      observedAt: "2026-07-29T07:30:00-03:00",
      recordedAt: "2026-07-29T07:34:00-03:00",
      eastMoisture: 31,
      westMoisture: 32,
      observedRainMm: 0,
      reservoirPercent: 64
    },
    day1: {
      id: "snapshot.day-1",
      observedAt: "2026-07-30T07:30:00-03:00",
      recordedAt: "2026-07-30T07:36:00-03:00",
      eastMoisture: 16,
      westMoisture: 31,
      observedRainMm: 0,
      forecastRainChance: 70,
      reservoirPercent: 62
    },
    returned: {
      id: "snapshot.return",
      observedAt: "2026-07-30T08:20:00-03:00",
      recordedAt: "2026-07-30T08:24:00-03:00",
      eastBefore: 15,
      observedRainMm: 0,
      appliedLiters: 8,
      eastAfter: 26,
      waitMinutes: 20
    }
  },
  modules: {
    hydrology: {
      id: "module.hydrology@1",
      name: "Hidrografia",
      reading: "O Leste caiu de 31% para 16%. Propõe verificar e aplicar até 8 L se a leitura de campo for ≤18%.",
      limit: "Interpreta umidade e fluxo; não observa chuva futura nem autoriza ação."
    },
    climate: {
      id: "module.climate@1",
      name: "Clima",
      reading: "Há 70% de previsão de chuva em 6 h. Recomenda esperar ou buscar evidência antes de consumir água.",
      limit: "Previsão não é chuva observada e não substitui a leitura do canteiro."
    }
  },
  tension: {
    id: "tension.east-dryness",
    title: "Secura localizada × chuva prevista",
    summary: "O Leste está abaixo de 20%, mas há previsão de chuva. Agir agora, esperar ou buscar evidência?"
  },
  mission: {
    id: "mission.inspect-water-east",
    title: "Verificar e cuidar do Canteiro Leste",
    instruction:
      "Meça a umidade. Se estiver em até 18% e não houver chuva observada, aplique 8 L. Meça novamente após 20 minutos.",
    cost: "25 min · máximo 8 L",
    acceptedEvidence: "leitura anterior, chuva observada, volume aplicado e leitura posterior",
    grantId: "grant.agent-proposal-only"
  }
} as const;

export type PrototypeReceipt = {
  receiptId: string;
  worldId: string;
  missionId: string;
  tensionId: string;
  decision: "partial_accept" | "pending_evidence" | "composted" | "rejected";
  acceptedClaims: string[];
  correctedClaims: string[];
  rejectedClaims: string[];
  sourceSnapshotRefs: string[];
  moduleVersions: string[];
  grantRef: string;
  mutation: null | {
    entityId: "entity.bed-east";
    from: "dry_attention";
    to: "recovering";
    dataRef: "snapshot.return";
    worldPatchId: "worldPatch.east-recovering";
  };
};

export type AnattaPrototypeSession = {
  phase: PrototypePhase;
  selectedId: string;
  activeLens: LensId;
  missionChoice: MissionChoice | null;
  claimDecisions: Record<ClaimId, ClaimDecision | null>;
  receipt: PrototypeReceipt | null;
  mutationCommitted: boolean;
  inspectedRef: string | null;
  notice: string | null;
};

export type PrototypeAction =
  | { type: "show_diff" }
  | { type: "focus_tension" }
  | { type: "set_lens"; lens: LensId }
  | { type: "open_mission" }
  | { type: "choose_mission"; choice: MissionChoice }
  | { type: "return_evidence" }
  | { type: "review_agent_proposal" }
  | { type: "open_gate" }
  | { type: "decide_claim"; claimId: ClaimId; decision: ClaimDecision }
  | { type: "emit_receipt" }
  | { type: "commit_mutation" }
  | { type: "close_session" }
  | { type: "inspect_ref"; dataRef: string | null }
  | { type: "reset" };

export const INITIAL_PROTOTYPE_SESSION: AnattaPrototypeSession = {
  phase: "quiet",
  selectedId: ANATTA_FIXTURE.world.id,
  activeLens: "compare",
  missionChoice: null,
  claimDecisions: {
    east_watered: null,
    east_recovering: null,
    whole_garden_resolved: null
  },
  receipt: null,
  mutationCommitted: false,
  inspectedRef: null,
  notice: null
};

const CANONICAL_CLAIM_DECISIONS: Record<ClaimId, ClaimDecision> = {
  east_watered: "accept",
  east_recovering: "correct",
  whole_garden_resolved: "reject"
};

function noMutationReceipt(decision: PrototypeReceipt["decision"]): PrototypeReceipt {
  return {
    receiptId: decision === "composted" ? "receipt.aurora-composted" : "receipt.aurora-pending",
    worldId: ANATTA_FIXTURE.world.id,
    missionId: ANATTA_FIXTURE.mission.id,
    tensionId: ANATTA_FIXTURE.tension.id,
    decision,
    acceptedClaims: [],
    correctedClaims: [],
    rejectedClaims: [],
    sourceSnapshotRefs: [ANATTA_FIXTURE.snapshots.day0.id, ANATTA_FIXTURE.snapshots.day1.id],
    moduleVersions: [ANATTA_FIXTURE.modules.hydrology.id, ANATTA_FIXTURE.modules.climate.id],
    grantRef: ANATTA_FIXTURE.mission.grantId,
    mutation: null
  };
}

function canonicalReceipt(): PrototypeReceipt {
  return {
    receiptId: "receipt.aurora-001",
    worldId: ANATTA_FIXTURE.world.id,
    missionId: ANATTA_FIXTURE.mission.id,
    tensionId: ANATTA_FIXTURE.tension.id,
    decision: "partial_accept",
    acceptedClaims: ["claim.east-watered"],
    correctedClaims: ["claim.east-status:recovering"],
    rejectedClaims: ["claim.whole-garden-risk-resolved"],
    sourceSnapshotRefs: [
      ANATTA_FIXTURE.snapshots.day0.id,
      ANATTA_FIXTURE.snapshots.day1.id,
      ANATTA_FIXTURE.snapshots.returned.id
    ],
    moduleVersions: [ANATTA_FIXTURE.modules.hydrology.id, ANATTA_FIXTURE.modules.climate.id],
    grantRef: ANATTA_FIXTURE.mission.grantId,
    mutation: {
      entityId: "entity.bed-east",
      from: "dry_attention",
      to: "recovering",
      dataRef: "snapshot.return",
      worldPatchId: "worldPatch.east-recovering"
    }
  };
}

export function hasCanonicalGateDecision(session: AnattaPrototypeSession): boolean {
  return (Object.keys(CANONICAL_CLAIM_DECISIONS) as ClaimId[]).every(
    (claimId) => session.claimDecisions[claimId] === CANONICAL_CLAIM_DECISIONS[claimId]
  );
}

export function prototypeReducer(
  session: AnattaPrototypeSession,
  action: PrototypeAction
): AnattaPrototypeSession {
  switch (action.type) {
    case "show_diff":
      return {
        ...session,
        phase: "diff_available",
        selectedId: ANATTA_FIXTURE.source.id,
        notice: "O diff é observado; previsão e fato continuam separados."
      };
    case "focus_tension":
      return {
        ...session,
        phase: "tension_focused",
        selectedId: ANATTA_FIXTURE.tension.id,
        notice: null
      };
    case "set_lens":
      return { ...session, activeLens: action.lens, notice: null };
    case "open_mission":
      return {
        ...session,
        phase: "mission_selected",
        selectedId: ANATTA_FIXTURE.mission.id,
        notice: null
      };
    case "choose_mission":
      if (action.choice === "delegate") {
        return {
          ...session,
          missionChoice: action.choice,
          notice: "Bloqueado pelo grant: o agente pode propor, mas não executar irrigação física."
        };
      }
      if (action.choice === "ask_evidence") {
        return {
          ...session,
          missionChoice: action.choice,
          phase: "receipt_issued",
          receipt: noMutationReceipt("pending_evidence"),
          selectedId: "receipt.aurora-pending",
          notice: "Missão pendente. Nenhuma geografia mudou."
        };
      }
      if (action.choice === "compost") {
        return {
          ...session,
          missionChoice: action.choice,
          phase: "receipt_issued",
          receipt: noMutationReceipt("composted"),
          selectedId: "receipt.aurora-composted",
          notice: "Tensão compostada sem culpa e sem mutação."
        };
      }
      return {
        ...session,
        missionChoice: action.choice,
        phase: "offscreen_action",
        selectedId: ANATTA_FIXTURE.mission.id,
        notice: "A interface deve ser fechável: a ação acontece no mundo real."
      };
    case "return_evidence":
      return {
        ...session,
        phase: "evidence_returned",
        selectedId: ANATTA_FIXTURE.snapshots.returned.id,
        notice: "Salto temporal explícito: uma fonte sintética retornou."
      };
    case "review_agent_proposal":
      return {
        ...session,
        phase: "agent_proposal",
        selectedId: "proposal.local-recovery",
        notice: "O agente normalizou a evidência e propôs; ainda não decidiu."
      };
    case "open_gate":
      return {
        ...session,
        phase: "human_gate",
        selectedId: "decision.partial-accept",
        notice: null
      };
    case "decide_claim":
      return {
        ...session,
        claimDecisions: { ...session.claimDecisions, [action.claimId]: action.decision },
        notice: null
      };
    case "emit_receipt": {
      const canonical = hasCanonicalGateDecision(session);
      return {
        ...session,
        phase: "receipt_issued",
        selectedId: canonical ? "receipt.aurora-001" : "receipt.aurora-rejected",
        receipt: canonical ? canonicalReceipt() : { ...noMutationReceipt("rejected"), receiptId: "receipt.aurora-rejected" },
        notice: canonical
          ? "Receipt parcial emitido. A mutação ainda não foi aplicada."
          : "Receipt de rejeição emitido. Nenhuma mutação foi autorizada."
      };
    }
    case "commit_mutation":
      if (!session.receipt?.mutation) return session;
      return {
        ...session,
        phase: "mutation_committed",
        selectedId: session.receipt.mutation.entityId,
        mutationCommitted: true,
        notice: "Somente o Canteiro Leste mudou para recuperação."
      };
    case "close_session":
      return { ...session, phase: "session_closed", notice: "Sessão encerrada com receipt legível." };
    case "inspect_ref":
      return { ...session, inspectedRef: action.dataRef };
    case "reset":
      return INITIAL_PROTOTYPE_SESSION;
  }
}

export const PHASE_ORDER: readonly PrototypePhase[] = [
  "quiet",
  "diff_available",
  "tension_focused",
  "mission_selected",
  "offscreen_action",
  "evidence_returned",
  "agent_proposal",
  "human_gate",
  "receipt_issued",
  "mutation_committed",
  "session_closed"
] as const;

export function phaseProgress(phase: PrototypePhase): number {
  return PHASE_ORDER.indexOf(phase) / (PHASE_ORDER.length - 1);
}

export function phaseLabel(phase: PrototypePhase): string {
  const labels: Record<PrototypePhase, string> = {
    quiet: "mundo em repouso",
    diff_available: "diff observado",
    tension_focused: "tensão em foco",
    mission_selected: "missão escolhida",
    offscreen_action: "ação fora da tela",
    evidence_returned: "evidência retornou",
    agent_proposal: "proposta do agente",
    human_gate: "gate humano",
    receipt_issued: "receipt emitido",
    mutation_committed: "mutação localizada",
    session_closed: "sessão encerrada"
  };
  return labels[phase];
}

export function phaseAtLeast(session: AnattaPrototypeSession, phase: PrototypePhase): boolean {
  return PHASE_ORDER.indexOf(session.phase) >= PHASE_ORDER.indexOf(phase);
}
