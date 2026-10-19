import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { lazy, Suspense } from "react";
import { saveAction, loadCoordination, createAction, loadActionCreationOptions } from "./world/clients/actionBoardClient";
const ActionBoard = lazy(() => import("./components/ActionBoard").then(module => ({ default: module.ActionBoard })));
const isBoard = /^\/(demo\/)?board\/?$/.test(window.location.pathname);
import { ErrorBoundary } from "./components/ErrorBoundary";
import { browserApplication } from "./infrastructure/browserApplication";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      {isBoard ? <Suspense fallback={<p role="status">Loading wiki…</p>}><ActionBoard operator={browserApplication.operator} save={saveAction} create={createAction} loadCreationOptions={loadActionCreationOptions} loadCoordination={loadCoordination} demo={window.location.pathname.startsWith("/demo/")} /></Suspense> : <App ports={browserApplication} />}
    </ErrorBoundary>
  </React.StrictMode>
);
