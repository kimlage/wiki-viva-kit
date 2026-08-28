// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { APPEARANCE_STORAGE_KEY } from "../data/appearance";
import { configureLanguage, t } from "../data/i18n";
import { AppearanceControl } from "./AppearanceControl";

beforeEach(() => {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, String(value)); }
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-wiki-theme");
  document.documentElement.removeAttribute("data-wiki-density");
  document.documentElement.style.removeProperty("color-scheme");
  configureLanguage("en");
});

describe("AppearanceControl", () => {
  it("exposes labelled theme and density controls with selection state", async () => {
    configureLanguage("en");
    render(<AppearanceControl />);

    expect(screen.getByLabelText(t("appearance.open"))).toBeTruthy();
    expect(screen.getByRole("region", { name: t("appearance.panel") })).toBeTruthy();
    expect(screen.getByRole("group", { name: t("appearance.theme.label") })).toBeTruthy();
    expect(screen.getByRole("group", { name: t("appearance.density.label") })).toBeTruthy();
    expect(screen.getByRole("button", { name: t("appearance.theme.use", { theme: t("appearance.theme.night-mission-control") }) }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: t("appearance.density.use", { density: t("appearance.density.balanced") }) }).getAttribute("aria-pressed")).toBe("true");

    await waitFor(() => {
      expect(document.documentElement.dataset.wikiTheme).toBe("night-mission-control");
      expect(document.documentElement.dataset.wikiDensity).toBe("balanced");
    });
  });

  it("switches and persists preferences without changing the route or replacing the canvas", async () => {
    configureLanguage("en");
    window.history.replaceState({}, "", "/w?q=evidence&reader=1");
    render(
      <>
        <AppearanceControl />
        <canvas data-testid="world-canvas" />
      </>
    );
    const routeBefore = window.location.href;
    const canvasBefore = screen.getByTestId("world-canvas");

    fireEvent.click(screen.getByRole("button", {
      name: t("appearance.theme.use", { theme: t("appearance.theme.luminous-observatory") })
    }));
    fireEvent.click(screen.getByRole("button", {
      name: t("appearance.density.use", { density: t("appearance.density.command") })
    }));

    await waitFor(() => {
      expect(document.documentElement.dataset.wikiTheme).toBe("luminous-observatory");
      expect(document.documentElement.dataset.wikiDensity).toBe("command");
      expect(JSON.parse(window.localStorage.getItem(APPEARANCE_STORAGE_KEY) || "{}")).toEqual({
        theme: "luminous-observatory",
        density: "command"
      });
    });
    expect(window.location.href).toBe(routeBefore);
    expect(screen.getByTestId("world-canvas")).toBe(canvasBefore);
    expect(canvasBefore.isConnected).toBe(true);
  });

  it("restores a persisted choice and keeps every new visible label in i18n", async () => {
    configureLanguage("pt-BR");
    window.localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({
      theme: "luminous-observatory",
      density: "focus"
    }));
    render(<AppearanceControl />);

    await waitFor(() => {
      expect(document.documentElement.dataset.wikiTheme).toBe("luminous-observatory");
      expect(document.documentElement.dataset.wikiDensity).toBe("focus");
    });

    const expectedVisibleCopy = [
      "appearance.shortLabel",
      "appearance.title",
      "appearance.description",
      "appearance.theme.label",
      "appearance.theme.luminous-observatory",
      "appearance.theme.luminous-observatory.description",
      "appearance.theme.night-mission-control",
      "appearance.theme.night-mission-control.description",
      "appearance.density.label",
      "appearance.density.focus",
      "appearance.density.balanced",
      "appearance.density.command",
      "appearance.density.focus.description"
    ].map((key) => t(key));

    for (const copy of expectedVisibleCopy) {
      expect(screen.getByText(copy)).toBeTruthy();
    }
  });
});
