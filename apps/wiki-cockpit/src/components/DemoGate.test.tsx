// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CORE_DEMO_SCENARIO_IDS } from "../data/demoScenarios";
import { configureLanguage } from "../data/i18n";
import { DemoGate } from "./DemoGate";

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("DemoGate validation labs", () => {
  it("keeps the seven core scenarios discoverable in one collapsed accessible gallery", () => {
    const { container } = render(<DemoGate />);

    expect(container.querySelectorAll(".demoGateDoor")).toHaveLength(5);
    const details = container.querySelector<HTMLDetailsElement>(".demoValidationLabs");
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false);

    const summary = screen.getByText("Validation labs").closest("summary");
    expect(summary).not.toBeNull();
    fireEvent.click(summary!);
    expect(details!.open).toBe(true);

    const links = [...container.querySelectorAll<HTMLAnchorElement>(".demoValidationLab")];
    expect(links).toHaveLength(7);
    expect(links.map((link) => link.dataset.demoScenario)).toEqual([
      ...CORE_DEMO_SCENARIO_IDS
    ]);
    for (const link of links) {
      expect(link.getAttribute("href")).toContain(
        `demo_scenario=${link.dataset.demoScenario}`
      );
      expect(link.getAttribute("href")).toContain("center=");
      expect(link.getAttribute("href")).toContain("view=");
    }
  });

  it("ships the gallery contract in Portuguese as well as English", () => {
    configureLanguage("pt-BR");
    render(<DemoGate />);

    expect(screen.getByText("Laboratórios de validação")).toBeTruthy();
    expect(screen.getByText("Ciclo de vida das fontes")).toBeTruthy();
    expect(screen.getByText("6 páginas")).toBeTruthy();
  });
});
