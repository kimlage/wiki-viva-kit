// The last line of defense: any render-time throw anywhere in the tree used to
// be a permanent white screen. This boundary shows an honest panel with the
// error and a reload affordance instead — the cockpit must degrade, not vanish.

import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("cockpit render crash:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="workspace">
        <section className="panel">
          <h1>O cockpit quebrou ao renderizar</h1>
          <p>
            <code>{this.state.error.message}</code>
          </p>
          <p>
            <button className="btn btn--primary" onClick={() => window.location.reload()} type="button">
              Recarregar
            </button>
          </p>
        </section>
      </main>
    );
  }
}
