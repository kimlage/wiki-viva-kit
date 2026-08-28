import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { browserApplication } from "./infrastructure/browserApplication";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App ports={browserApplication} />
    </ErrorBoundary>
  </React.StrictMode>
);
