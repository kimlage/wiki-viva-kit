import { lazy, Suspense, useMemo, useReducer } from "react";
import { prototypeReducer, INITIAL_PROTOTYPE_SESSION, PROTOTYPE_VARIANTS } from "./model";
import {
  canUseWebGL,
  DataRefInspector,
  PrototypeBrand,
  PrototypeSwitcher,
  SemanticMap2D,
  SessionDebug,
  SessionProgress,
  usePrototypeQuery,
  useReducedMotion
} from "./shared";
import "./prototype.css";

const OrganismVariant = lazy(() => import("./variants/organism/OrganismVariant"));
const TableVariant = lazy(() => import("./variants/table/TableVariant"));
const ScalesVariant = lazy(() => import("./variants/scales/ScalesVariant"));
const SandVariant = lazy(() => import("./variants/sand/SandVariant"));

export function AnattaWorldsPrototype() {
  const [session, dispatch] = useReducer(prototypeReducer, INITIAL_PROTOTYPE_SESSION);
  const reducedMotion = useReducedMotion();
  const query = usePrototypeQuery();
  const webgl = useMemo(() => canUseWebGL(), []);
  const rendererMode = query.renderer === "2d" || !webgl ? "2d" : "3d";
  const selectedVariant = PROTOTYPE_VARIANTS.find((variant) => variant.id === query.variant) ?? PROTOTYPE_VARIANTS[0];
  const Variant = query.variant === "table"
    ? TableVariant
    : query.variant === "scales"
      ? ScalesVariant
      : query.variant === "sand"
        ? SandVariant
        : OrganismVariant;

  return (
    <div
      className={`awPrototype awVariant-${query.variant}`}
      data-prototype-variant={query.variant}
      data-prototype-phase={session.phase}
      data-renderer-mode={rendererMode}
      data-claim-decisions={JSON.stringify(session.claimDecisions)}
    >
      <PrototypeBrand variantName={`${selectedVariant.key} — ${selectedVariant.name}`} />
      <SessionProgress session={session} />

      {rendererMode === "2d" ? (
        <SemanticMap2D session={session} dispatch={dispatch} />
      ) : (
        <Suspense fallback={<div className="awPrototypeLoading" role="status">Montando o mundo sintético…</div>}>
          <Variant
            session={session}
            dispatch={dispatch}
            rendererMode={rendererMode}
            reducedMotion={reducedMotion}
          />
        </Suspense>
      )}

      <DataRefInspector session={session} dispatch={dispatch} />
      <SessionDebug session={session} />
      <PrototypeSwitcher
        current={query.variant}
        rendererMode={rendererMode}
        onVariant={(variant) => query.replace({ variant })}
        onRenderer={(renderer) => query.replace({ renderer })}
      />
      {!webgl && (
        <p className="awWebglNotice" role="status">
          WebGL indisponível; o equivalente 2D preserva o mesmo estado e todas as decisões.
        </p>
      )}
    </div>
  );
}

export default AnattaWorldsPrototype;
