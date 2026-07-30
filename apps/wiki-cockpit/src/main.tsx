import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { browserApplication } from "./infrastructure/browserApplication";

const AnattaWorldsPrototype = lazy(
  () => import("../labs/anatta-worlds/AnattaWorldsPrototype")
);
const prototypeRoute = window.location.pathname === "/prototype/anatta-worlds";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      {prototypeRoute ? (
        <Suspense fallback={<main role="status">Abrindo laboratório Anatta Worlds…</main>}>
          <AnattaWorldsPrototype />
        </Suspense>
      ) : (
        <App ports={browserApplication} />
      )}
    </ErrorBoundary>
  </React.StrictMode>
);
