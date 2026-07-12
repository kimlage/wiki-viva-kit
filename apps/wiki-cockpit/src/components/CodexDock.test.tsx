// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import { CODEX_UNAVAILABLE } from "../types";
import { CodexDock } from "./CodexDock";

const outdated = {
  ...CODEX_UNAVAILABLE,
  operator_outdated: true,
  reason: "the local operator is outdated; restart it"
};

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("CodexDock stale-operator recovery", () => {
  it("shows one actionable English restart step and exposes re-verification", () => {
    const reverify = vi.fn();
    configureLanguage("en");
    render(
      <CodexDock
        capability={outdated}
        busy={false}
        onReverify={reverify}
        onClose={() => undefined}
      />
    );

    expect(screen.getByText("Operator up to date")).toBeTruthy();
    expect(screen.getByText(/Restart the local operator/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Re-verify" }));
    expect(reverify).toHaveBeenCalledTimes(1);
  });

  it("renders the same restart and reverify path in Portuguese", () => {
    configureLanguage("pt-BR");
    render(
      <CodexDock
        capability={outdated}
        busy={false}
        onReverify={() => undefined}
        onClose={() => undefined}
      />
    );

    expect(screen.getByText("Operador atualizado")).toBeTruthy();
    expect(screen.getByText(/Reinicie o operador local/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Re-verificar" })).toBeTruthy();
  });
});
