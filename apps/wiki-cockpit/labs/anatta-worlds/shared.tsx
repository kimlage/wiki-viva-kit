import type { Dispatch, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  ANATTA_FIXTURE,
  PHASE_ORDER,
  PROTOTYPE_VARIANTS,
  hasCanonicalGateDecision,
  phaseLabel,
  phaseProgress
} from "./model";
import type {
  AnattaPrototypeSession,
  ClaimDecision,
  ClaimId,
  LensId,
  MissionChoice,
  PrototypeAction,
  PrototypeVariantId,
  RendererMode
} from "./model";

type SessionProps = {
  session: AnattaPrototypeSession;
  dispatch: Dispatch<PrototypeAction>;
};

export function PrototypeBrand({ variantName }: { variantName: string }) {
  return (
    <header className="awBrand">
      <div>
        <span className="awEyebrow">Anatta Labs · laboratório Wayfinder</span>
        <strong>Anatta Worlds</strong>
      </div>
      <p>{variantName}</p>
      <span className="awSyntheticBadge">dados sintéticos</span>
    </header>
  );
}
export function SessionProgress({ session }: { session: AnattaPrototypeSession }) {
  return (
    <div className="awSessionProgress" aria-label={`Progresso: ${phaseLabel(session.phase)}`}>
      <span style={{ "--aw-progress": phaseProgress(session.phase) } as React.CSSProperties} />
      <small>{phaseLabel(session.phase)}</small>
    </div>
  );
}

export function IntentionCard({ onInspect }: { onInspect: () => void }) {
  return (
    <aside className="awIntentionCard">
      <span>intenção do mundo</span>
      <strong>{ANATTA_FIXTURE.world.name}</strong>
      <p>{ANATTA_FIXTURE.world.intention}</p>
      <button type="button" onClick={onInspect}>abrir dataRef</button>
    </aside>
  );
}

const MISSION_CHOICES: readonly { id: MissionChoice; label: string; note: string }[] = [
  { id: "do", label: "Fazer", note: "percurso canônico da comparação" },
  { id: "delegate", label: "Delegar", note: "o grant deve bloquear execução física" },
  { id: "ask_evidence", label: "Pedir evidência", note: "encerra pendente, sem mutação" },
  { id: "compost", label: "Compostar", note: "encerra sem culpa e sem mutação" }
];

const CLAIMS: readonly { id: ClaimId; copy: string; expected: ClaimDecision }[] = [
  { id: "east_watered", copy: "8 L foram aplicados no Canteiro Leste.", expected: "accept" },
  { id: "east_recovering", copy: "O Canteiro Leste está resolvido.", expected: "correct" },
  { id: "whole_garden_resolved", copy: "O risco climático da horta inteira foi resolvido.", expected: "reject" }
];

function RefButton({
  dataRef,
  dispatch,
  children
}: {
  dataRef: string;
  dispatch: Dispatch<PrototypeAction>;
  children?: ReactNode;
}) {
  return (
    <button
      type="button"
      className="awDataRef"
      onClick={() => dispatch({ type: "inspect_ref", dataRef })}
    >
      {children ?? dataRef}
    </button>
  );
}

function LensCompare({ session, dispatch }: SessionProps) {
  const lenses: readonly { id: LensId; label: string }[] = [
    { id: "hydrology", label: "Hidrografia" },
    { id: "climate", label: "Clima" },
    { id: "compare", label: "Comparar" }
  ];
  const showHydrology = session.activeLens !== "climate";
  const showClimate = session.activeLens !== "hydrology";
  return (
    <>
      <div className="awSegmented" role="group" aria-label="Lentes">
        {lenses.map((lens) => (
          <button
            key={lens.id}
            className={session.activeLens === lens.id ? "active" : ""}
            onClick={() => dispatch({ type: "set_lens", lens: lens.id })}
            type="button"
          >
            {lens.label}
          </button>
        ))}
      </div>
      <div className="awLensGrid">
        {showHydrology && (
          <article className="awLensCard hydro">
            <span>{ANATTA_FIXTURE.modules.hydrology.name}</span>
            <p>{ANATTA_FIXTURE.modules.hydrology.reading}</p>
            <small>{ANATTA_FIXTURE.modules.hydrology.limit}</small>
            <RefButton dataRef={ANATTA_FIXTURE.modules.hydrology.id} dispatch={dispatch} />
          </article>
        )}
        {showClimate && (
          <article className="awLensCard climate">
            <span>{ANATTA_FIXTURE.modules.climate.name}</span>
            <p>{ANATTA_FIXTURE.modules.climate.reading}</p>
            <small>{ANATTA_FIXTURE.modules.climate.limit}</small>
            <RefButton dataRef={ANATTA_FIXTURE.modules.climate.id} dispatch={dispatch} />
          </article>
        )}
      </div>
    </>
  );
}

export function DecisionSurface({
  session,
  dispatch,
  title = "Superfície de precisão"
}: SessionProps & { title?: string }) {
  const allClaimsDecided = Object.values(session.claimDecisions).every(Boolean);

  return (
    <section className="awDecisionSurface" aria-label={title}>
      <header>
        <div>
          <span>{title}</span>
          <strong>{phaseLabel(session.phase)}</strong>
        </div>
        <RefButton dataRef={session.selectedId} dispatch={dispatch}>dataRef ↗</RefButton>
      </header>

      {session.phase === "quiet" && (
        <div className="awSurfaceBody awCallToAction">
          <span className="awKicker">uma mudança está disponível</span>
          <h2>O mundo não acusa. Ele oferece um diff verificável.</h2>
          <p>Compare dois snapshots antes de atribuir urgência ou causalidade.</p>
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "show_diff" })}>
            Ver o diff
          </button>
        </div>
      )}

      {session.phase === "diff_available" && (
        <div className="awSurfaceBody">
          <span className="awKicker">snapshot.day-0 → snapshot.day-1</span>
          <h2>O Leste caiu de 31% para 16%.</h2>
          <div className="awMetricRow">
            <div><span>Leste</span><strong>−15 pp</strong></div>
            <div><span>Oeste</span><strong>−1 pp</strong></div>
            <div><span>chuva observada</span><strong>0 mm</strong></div>
          </div>
          <p>70% é previsão para as próximas 6 h — não chuva observada.</p>
          <div className="awActions">
            <RefButton dataRef={ANATTA_FIXTURE.snapshots.day0.id} dispatch={dispatch}>snapshot anterior</RefButton>
            <RefButton dataRef={ANATTA_FIXTURE.snapshots.day1.id} dispatch={dispatch}>snapshot atual</RefButton>
            <button className="awPrimary" type="button" onClick={() => dispatch({ type: "focus_tension" })}>
              Focar a tensão
            </button>
          </div>
        </div>
      )}

      {session.phase === "tension_focused" && (
        <div className="awSurfaceBody">
          <span className="awKicker">duas leituras · uma evidência</span>
          <h2>{ANATTA_FIXTURE.tension.title}</h2>
          <p>{ANATTA_FIXTURE.tension.summary}</p>
          <LensCompare session={session} dispatch={dispatch} />
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "open_mission" })}>
            Abrir missão possível
          </button>
        </div>
      )}

      {session.phase === "mission_selected" && (
        <div className="awSurfaceBody">
          <span className="awKicker">missão real · quatro saídas válidas</span>
          <h2>{ANATTA_FIXTURE.mission.title}</h2>
          <p>{ANATTA_FIXTURE.mission.instruction}</p>
          <dl className="awMissionFacts">
            <div><dt>custo importado</dt><dd>{ANATTA_FIXTURE.mission.cost}</dd></div>
            <div><dt>evidência aceita</dt><dd>{ANATTA_FIXTURE.mission.acceptedEvidence}</dd></div>
          </dl>
          <div className="awChoiceGrid">
            {MISSION_CHOICES.map((choice) => (
              <button
                key={choice.id}
                type="button"
                onClick={() => dispatch({ type: "choose_mission", choice: choice.id })}
              >
                <strong>{choice.label}</strong>
                <small>{choice.note}</small>
              </button>
            ))}
          </div>
        </div>
      )}

      {session.phase === "offscreen_action" && (
        <div className="awSurfaceBody awCallToAction">
          <span className="awKicker">o jogo continua fora da tela</span>
          <h2>O mundo aguarda evidência, não tempo de tela.</h2>
          <p>Na demo, o próximo botão faz um salto temporal explícito e injeta somente a fixture sintética.</p>
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "return_evidence" })}>
            Simular retorno da fonte sintética
          </button>
        </div>
      )}

      {session.phase === "evidence_returned" && (
        <div className="awSurfaceBody">
          <span className="awKicker">nova evidência · ainda sem mutação</span>
          <h2>15% → 26% após 8 L e 20 minutos.</h2>
          <div className="awMetricRow">
            <div><span>antes</span><strong>15%</strong></div>
            <div><span>aplicado</span><strong>8 L</strong></div>
            <div><span>depois</span><strong>26%</strong></div>
          </div>
          <RefButton dataRef={ANATTA_FIXTURE.snapshots.returned.id} dispatch={dispatch}>abrir evidência retornada</RefButton>
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "review_agent_proposal" })}>
            Ver proposta do agente
          </button>
        </div>
      )}

      {session.phase === "agent_proposal" && (
        <div className="awSurfaceBody">
          <span className="awKicker">proposal mode · sem autoridade humana</span>
          <h2>Proposta: marcar apenas o Leste como “em recuperação”.</h2>
          <p>O agente normalizou os dados. O grant permite propor, não aprovar, publicar ou alterar o mundo.</p>
          <dl className="awMissionFacts">
            <div><dt>grant</dt><dd>{ANATTA_FIXTURE.mission.grantId}</dd></div>
            <div><dt>impacto máximo</dt><dd>entity.bed-east</dd></div>
          </dl>
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "open_gate" })}>
            Abrir gate humano
          </button>
        </div>
      )}

      {session.phase === "human_gate" && (
        <div className="awSurfaceBody">
          <span className="awKicker">gate humano · revisão claim a claim</span>
          <h2>Conceda significado sem ampliar a evidência.</h2>
          <div className="awClaimList">
            {CLAIMS.map((claim) => (
              <article key={claim.id}>
                <p>{claim.copy}</p>
                <div role="group" aria-label={`Decisão sobre: ${claim.copy}`}>
                  {(["accept", "correct", "reject"] as ClaimDecision[]).map((decision) => (
                    <button
                      type="button"
                      key={decision}
                      className={session.claimDecisions[claim.id] === decision ? "active" : ""}
                      onClick={() => dispatch({ type: "decide_claim", claimId: claim.id, decision })}
                    >
                      {decision === "accept" ? "aceitar" : decision === "correct" ? "corrigir" : "rejeitar"}
                    </button>
                  ))}
                </div>
                {session.claimDecisions[claim.id] && session.claimDecisions[claim.id] !== claim.expected && (
                  <small>Essa leitura não autoriza a mutação localizada da comparação.</small>
                )}
              </article>
            ))}
          </div>
          <button
            className="awPrimary"
            type="button"
            disabled={!allClaimsDecided}
            onClick={() => dispatch({ type: "emit_receipt" })}
          >
            Emitir receipt
          </button>
          {allClaimsDecided && (
            <small className={hasCanonicalGateDecision(session) ? "awGateReady" : "awGateRejected"}>
              {hasCanonicalGateDecision(session)
                ? "Gate parcial coerente: aceitar · corrigir · rejeitar."
                : "A combinação atual produzirá receipt sem mutação."}
            </small>
          )}
        </div>
      )}

      {session.phase === "receipt_issued" && session.receipt && (
        <div className="awSurfaceBody">
          <span className="awKicker">receipt tipado · antes da mutação</span>
          <h2>{session.receipt.receiptId}</h2>
          <p>
            Decisão: <strong>{session.receipt.decision}</strong>. Impacto autorizado:{" "}
            <strong>{session.receipt.mutation?.entityId ?? "nenhum"}</strong>.
          </p>
          <RefButton dataRef={session.receipt.receiptId} dispatch={dispatch}>inspecionar receipt</RefButton>
          {session.receipt.mutation ? (
            <button className="awPrimary" type="button" onClick={() => dispatch({ type: "commit_mutation" })}>
              Aplicar mutação autorizada
            </button>
          ) : (
            <button className="awPrimary" type="button" onClick={() => dispatch({ type: "reset" })}>
              Recomeçar o percurso canônico
            </button>
          )}
        </div>
      )}

      {session.phase === "mutation_committed" && (
        <div className="awSurfaceBody">
          <span className="awKicker">consequência localizada</span>
          <h2>Somente o Canteiro Leste está em recuperação.</h2>
          <p>15% → 26%; 8 L registrados; recuperação parcial aceita por gate humano.</p>
          <div className="awActions">
            <RefButton dataRef="worldPatch.east-recovering" dispatch={dispatch}>worldPatch</RefButton>
            <RefButton dataRef="receipt.aurora-001" dispatch={dispatch}>receipt</RefButton>
            <button className="awPrimary" type="button" onClick={() => dispatch({ type: "close_session" })}>
              Encerrar com receipt
            </button>
          </div>
        </div>
      )}

      {session.phase === "session_closed" && (
        <div className="awSurfaceBody awCallToAction">
          <span className="awKicker">sessão voluntária encerrada</span>
          <h2>O mundo preserva a consequência; não cria uma nova cobrança.</h2>
          <button className="awPrimary" type="button" onClick={() => dispatch({ type: "reset" })}>
            Reiniciar comparação
          </button>
        </div>
      )}

      {session.notice && <p className="awNotice" role="status">{session.notice}</p>}
    </section>
  );
}

export function DataRefInspector({ session, dispatch }: SessionProps) {
  if (!session.inspectedRef) return null;
  const ref = session.inspectedRef;
  const receipt = ref.startsWith("receipt") ? session.receipt : null;
  return (
    <aside className="awRefInspector" aria-label="Inspector de dataRef">
      <header>
        <div><span>referência verificável</span><strong>{ref}</strong></div>
        <button type="button" onClick={() => dispatch({ type: "inspect_ref", dataRef: null })}>×</button>
      </header>
      {ref === ANATTA_FIXTURE.world.intentionId && <p>{ANATTA_FIXTURE.world.intention}</p>}
      {ref === ANATTA_FIXTURE.snapshots.day0.id && <pre>{JSON.stringify(ANATTA_FIXTURE.snapshots.day0, null, 2)}</pre>}
      {ref === ANATTA_FIXTURE.snapshots.day1.id && <pre>{JSON.stringify(ANATTA_FIXTURE.snapshots.day1, null, 2)}</pre>}
      {ref === ANATTA_FIXTURE.snapshots.returned.id && <pre>{JSON.stringify(ANATTA_FIXTURE.snapshots.returned, null, 2)}</pre>}
      {ref === ANATTA_FIXTURE.modules.hydrology.id && <p>{ANATTA_FIXTURE.modules.hydrology.limit}</p>}
      {ref === ANATTA_FIXTURE.modules.climate.id && <p>{ANATTA_FIXTURE.modules.climate.limit}</p>}
      {receipt && <pre>{JSON.stringify(receipt, null, 2)}</pre>}
      {!receipt && ![
        ANATTA_FIXTURE.world.intentionId,
        ANATTA_FIXTURE.snapshots.day0.id,
        ANATTA_FIXTURE.snapshots.day1.id,
        ANATTA_FIXTURE.snapshots.returned.id,
        ANATTA_FIXTURE.modules.hydrology.id,
        ANATTA_FIXTURE.modules.climate.id
      ].includes(ref as never) && (
        <dl>
          <div><dt>tipo</dt><dd>{ref.split(".")[0]}</dd></div>
          <div><dt>estado atual</dt><dd>{phaseLabel(session.phase)}</dd></div>
          <div><dt>fonte</dt><dd>{ANATTA_FIXTURE.source.id}</dd></div>
          <div><dt>alternativa textual</dt><dd>Disponível nesta superfície 2D.</dd></div>
        </dl>
      )}
    </aside>
  );
}

export function SemanticMap2D({ session, dispatch }: SessionProps) {
  const changed = session.mutationCommitted;
  return (
    <main className="awSemanticMap" aria-label="Equivalente 2D do Jardim Aurora">
      <div className="awMapHeader">
        <div>
          <span>equivalente 2D · mesma sessão</span>
          <h1>{ANATTA_FIXTURE.world.name}</h1>
          <p>{ANATTA_FIXTURE.world.intention}</p>
        </div>
        <RefButton dataRef={ANATTA_FIXTURE.world.intentionId} dispatch={dispatch} />
      </div>
      <div className="awMapLayout">
        <section className="awPlanGrid" aria-label="Canteiros">
          <button type="button" className="awBed west" onClick={() => dispatch({ type: "inspect_ref", dataRef: "entity.bed-west" })}>
            <span>Oeste</span><strong>31%</strong><small>sem mutação</small>
          </button>
          <button type="button" className="awBed center" onClick={() => dispatch({ type: "inspect_ref", dataRef: "entity.bed-center" })}>
            <span>Centro</span><strong>estável</strong><small>sem mutação</small>
          </button>
          <button
            type="button"
            className={`awBed east ${changed ? "recovering" : "attention"}`}
            onClick={() => dispatch({
              type: "inspect_ref",
              dataRef: changed ? "worldPatch.east-recovering" : ANATTA_FIXTURE.tension.id
            })}
          >
            <span>Leste</span>
            <strong>{changed ? "26%" : "16%"}</strong>
            <small>{changed ? "em recuperação" : "tensão localizada"}</small>
          </button>
          <button type="button" className="awReservoir" onClick={() => dispatch({ type: "inspect_ref", dataRef: ANATTA_FIXTURE.source.id })}>
            reservatório · 62%
          </button>
        </section>
        <DecisionSurface session={session} dispatch={dispatch} title="Operação 2D equivalente" />
      </div>
    </main>
  );
}

export function PrototypeSwitcher({
  current,
  rendererMode,
  onVariant,
  onRenderer
}: {
  current: PrototypeVariantId;
  rendererMode: RendererMode;
  onVariant: (variant: PrototypeVariantId) => void;
  onRenderer: (mode: RendererMode) => void;
}) {
  const currentIndex = PROTOTYPE_VARIANTS.findIndex((variant) => variant.id === current);
  const cycle = (direction: -1 | 1) => {
    const nextIndex = (currentIndex + direction + PROTOTYPE_VARIANTS.length) % PROTOTYPE_VARIANTS.length;
    onVariant(PROTOTYPE_VARIANTS[nextIndex].id);
  };
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft") cycle(-1);
      if (event.key === "ArrowRight") cycle(1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });
  const selected = PROTOTYPE_VARIANTS[currentIndex] ?? PROTOTYPE_VARIANTS[0];
  return (
    <nav className="awPrototypeSwitcher" aria-label="Alternar protótipos">
      <button type="button" onClick={() => cycle(-1)} aria-label="Protótipo anterior">←</button>
      <div>
        <strong>{selected.key} — {selected.name}</strong>
        <span>{selected.promise}</span>
      </div>
      <button type="button" onClick={() => cycle(1)} aria-label="Próximo protótipo">→</button>
      <i aria-hidden />
      <button
        type="button"
        className={rendererMode === "2d" ? "active" : ""}
        onClick={() => onRenderer(rendererMode === "3d" ? "2d" : "3d")}
      >
        {rendererMode === "3d" ? "ver equivalente 2D" : "voltar ao 3D"}
      </button>
    </nav>
  );
}

export function SessionDebug({ session }: { session: AnattaPrototypeSession }) {
  return (
    <details className="awSessionDebug">
      <summary>estado compartilhado</summary>
      <pre>{JSON.stringify(session, null, 2)}</pre>
    </details>
  );
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

export function canUseWebGL(): boolean {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function usePrototypeQuery() {
  const read = () => {
    const params = new URLSearchParams(window.location.search);
    const variantParam = params.get("variant");
    const variant = PROTOTYPE_VARIANTS.some((item) => item.id === variantParam)
      ? variantParam as PrototypeVariantId
      : "organism";
    const renderer: RendererMode = params.get("renderer") === "2d" ? "2d" : "3d";
    return { variant, renderer };
  };
  const [query, setQuery] = useState(read);
  useEffect(() => {
    const sync = () => setQuery(read());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  const replace = (next: Partial<typeof query>) => {
    const merged = { ...query, ...next };
    const url = new URL(window.location.href);
    url.searchParams.set("variant", merged.variant);
    if (merged.renderer === "2d") url.searchParams.set("renderer", "2d");
    else url.searchParams.delete("renderer");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setQuery(merged);
  };
  return useMemo(() => ({ ...query, replace }), [query]);
}

export function PhaseDots({ session }: { session: AnattaPrototypeSession }) {
  const current = PHASE_ORDER.indexOf(session.phase);
  return (
    <div className="awPhaseDots" aria-hidden="true">
      {PHASE_ORDER.map((phase, index) => (
        <span key={phase} className={index <= current ? "done" : ""} />
      ))}
    </div>
  );
}
