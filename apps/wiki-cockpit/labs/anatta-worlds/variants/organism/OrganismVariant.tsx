import { Canvas } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ACESFilmicToneMapping,
  PCFSoftShadowMap,
  SRGBColorSpace
} from "three";
import type { AnattaVariantProps } from "../../contracts";
import { ANATTA_FIXTURE, phaseLabel } from "../../model";
import { DecisionSurface } from "../../shared";
import {
  BasinScene,
  type BeautyMetrics,
  type BeautyViewMode
} from "./beauty-slice/BasinScene";
import "./OrganismVariant.css";

const PERFORMANCE_BUDGET = {
  fps: 55,
  calls: 250,
  triangles: 1_500_000
} as const;

function compactNumber(value: number) {
  return new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}

function primaryActionLabel(
  phase: AnattaVariantProps["session"]["phase"],
  viewMode: BeautyViewMode
) {
  if (viewMode !== "exterior") return "Voltar à bacia";
  if (phase === "quiet") return "Ver o diff";
  if (phase === "diff_available") return "Focar a tensão";
  if (phase === "tension_focused") return "Entrar na Casa da Hidrografia";
  return "Abrir a mesa da hidrografia";
}

export default function OrganismVariant({
  session,
  dispatch,
  rendererMode,
  reducedMotion
}: AnattaVariantProps) {
  const [viewMode, setViewMode] = useState<BeautyViewMode>("exterior");
  const [interiorReady, setInteriorReady] = useState(false);
  const [metrics, setMetrics] = useState<BeautyMetrics | null>(null);
  const transitionTimer = useRef<number | null>(null);

  const clearTransition = useCallback(() => {
    if (transitionTimer.current !== null) {
      window.clearTimeout(transitionTimer.current);
      transitionTimer.current = null;
    }
  }, []);

  const enterModule = useCallback(() => {
    clearTransition();
    setInteriorReady(false);
    if (reducedMotion) {
      setViewMode("interior");
      return;
    }
    setViewMode("approaching");
    transitionTimer.current = window.setTimeout(() => {
      setViewMode("interior");
      transitionTimer.current = null;
    }, 820);
  }, [clearTransition, reducedMotion]);

  const exitModule = useCallback(() => {
    clearTransition();
    setInteriorReady(false);
    setViewMode("exterior");
  }, [clearTransition]);

  useEffect(() => clearTransition, [clearTransition]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  const selectTension = useCallback(() => {
    if (session.phase === "quiet") {
      dispatch({ type: "show_diff" });
      return;
    }
    if (session.phase === "diff_available") {
      dispatch({ type: "focus_tension" });
      return;
    }
    enterModule();
  }, [dispatch, enterModule, session.phase]);

  const runPrimaryAction = useCallback(() => {
    if (viewMode !== "exterior") {
      exitModule();
      return;
    }
    if (session.phase === "quiet") {
      dispatch({ type: "show_diff" });
      return;
    }
    if (session.phase === "diff_available") {
      dispatch({ type: "focus_tension" });
      return;
    }
    enterModule();
  }, [dispatch, enterModule, exitModule, session.phase, viewMode]);

  const budgetState = useMemo(() => {
    if (!metrics) return "measuring";
    return metrics.fps >= PERFORMANCE_BUDGET.fps
      && metrics.calls <= PERFORMANCE_BUDGET.calls
      && metrics.triangles <= PERFORMANCE_BUDGET.triangles
      ? "within"
      : "over";
  }, [metrics]);

  const eastStatus = session.mutationCommitted
    ? "26% · recuperação localizada autorizada"
    : "16% · tensão observada, ainda sem mutação";

  return (
    <main
      className={[
        "organismVariant",
        `organismVariant--${viewMode}`,
        reducedMotion ? "organismVariant--reducedMotion" : ""
      ].filter(Boolean).join(" ")}
      data-renderer={rendererMode}
      data-beauty-view={viewMode}
      data-interior-ready={interiorReady ? "true" : "false"}
      data-east-state={session.mutationCommitted ? "recovering" : "dry_attention"}
    >
      <section
        className="beautyStage"
        aria-labelledby="beauty-world-title"
        aria-describedby="beauty-world-description"
      >
        <div className="beautyWorldViewport">
          <Canvas
            shadows
            frameloop="always"
            dpr={[1, reducedMotion ? 1.1 : 1.25]}
            gl={{
              antialias: true,
              alpha: false,
              powerPreference: "high-performance",
              preserveDrawingBuffer: false,
              stencil: false
            }}
            onCreated={({ gl }) => {
              gl.outputColorSpace = SRGBColorSpace;
              gl.toneMapping = ACESFilmicToneMapping;
              gl.toneMappingExposure = 0.92;
              gl.shadowMap.type = PCFSoftShadowMap;
            }}
          >
            <BasinScene
              viewMode={viewMode}
              authorized={session.mutationCommitted}
              receiptVisible={Boolean(session.receipt)}
              reducedMotion={reducedMotion}
              consoleContent={(
                <DecisionSurface
                  session={session}
                  dispatch={dispatch}
                  title="Mesa da Hidrografia"
                />
              )}
              onEnter={enterModule}
              onExit={exitModule}
              onSelectTension={selectTension}
              onMetrics={setMetrics}
              onInteriorReached={() => setInteriorReady(true)}
            />
          </Canvas>
        </div>

        <div className="beautyOpticalFrame" aria-hidden="true" />

        {viewMode === "interior" && (
          <button className="beautyFixedExit" type="button" onClick={exitModule}>
            ← voltar à bacia
          </button>
        )}

        <header className="beautyIdentity">
          <span>Jardim Aurora · bacia 01</span>
          <h1 id="beauty-world-title">Bacia Viva</h1>
          <p id="beauty-world-description">
            Uma única microbacia autorada: nascente, corrente, margem, módulo e
            evidência compartilham o mesmo espaço.
          </p>
        </header>

        <aside className="beautyTension" aria-label="Tensão selecionada">
          <span aria-hidden="true" />
          <div>
            <small>{ANATTA_FIXTURE.tension.title}</small>
            <strong>{eastStatus}</strong>
          </div>
        </aside>

        <nav className="beautyContextRail" aria-label="Ação contextual da bacia">
          <div>
            <span>leitura atual</span>
            <strong>{phaseLabel(session.phase)}</strong>
          </div>
          <button type="button" onClick={runPrimaryAction}>
            {primaryActionLabel(session.phase, viewMode)}
          </button>
        </nav>

        <aside
          className="beautyPerformance"
          data-budget={budgetState}
          data-fps={metrics?.fps ?? ""}
          data-frame-ms={metrics?.frameMs ?? ""}
          data-calls={metrics?.calls ?? ""}
          data-triangles={metrics?.triangles ?? ""}
          data-geometries={metrics?.geometries ?? ""}
          data-textures={metrics?.textures ?? ""}
          data-first-frame-ms={metrics?.firstFrameMs ?? ""}
          aria-label="Telemetria do render"
        >
          <span>{budgetState === "within" ? "budget ok" : budgetState === "over" ? "revisar budget" : "medindo"}</span>
          {metrics && (
            <>
              <strong>{metrics.fps} fps</strong>
              <small>
                {metrics.calls} calls · {compactNumber(metrics.triangles)} tris
              </small>
            </>
          )}
        </aside>

        <p className="beautyInteractionHint">
          arraste para inspecionar · role para aproximar · selecione os marcadores
        </p>

        <div className="beautyScreenReader" aria-live="polite">
          {viewMode === "approaching"
            ? "Aproximando-se da Casa da Hidrografia."
            : viewMode === "interior"
              ? "Interior da Casa da Hidrografia. A mesa 2D preserva a seleção da bacia."
              : "Vista geral da Bacia Viva."}
        </div>
      </section>
    </main>
  );
}
