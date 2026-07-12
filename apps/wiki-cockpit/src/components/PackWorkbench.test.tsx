// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExperiencePackComposition, PageRecord } from "../types";
import { configureLanguage } from "../data/i18n";
import { PackWorkbench } from "./PackWorkbench";

const composition: ExperiencePackComposition = {
  schema_version: "wiki_experience_pack_composition.v1",
  core_version: "8.0.0",
  packs: [{ id: "example-pack", version: "1.2.3" }],
  block_packages: ["quadrant_lenses", "honest_signals"],
  slots: {
    views: [
      { pack: "example-pack", slot: "view.map", contribution: "example-pack.reference-map", mode: "append" },
      { pack: "example-pack", slot: "view.queue", contribution: "example-pack.review-queue", mode: "append" }
    ],
    commands: [{ pack: "example-pack", slot: "command.capture", contribution: "example-pack.capture", mode: "append" }],
    operations: [{ pack: "example-pack", slot: "operation.review", contribution: "example-pack.review", mode: "append" }],
    timelines: [{ pack: "example-pack", slot: "timeline.history", contribution: "example-pack.history", mode: "append" }]
  },
  presentation: {
    default_locale: "en",
    locales: {
      en: {
        "example-pack": "Example Knowledge",
        "example-pack.capture": "Capture",
        "example-pack.history": "Knowledge history",
        "example-pack.reference-map": "Reference map",
        "example-pack.review": "Review evidence",
        "example-pack.review-queue": "Review queue",
        example_pack_claim: "Claim",
        example_pack_source: "Source"
      },
      "pt-BR": {
        "example-pack": "Conhecimento de Exemplo",
        "example-pack.capture": "Capturar",
        "example-pack.history": "Histórico do conhecimento",
        "example-pack.reference-map": "Mapa de referências",
        "example-pack.review": "Revisar evidências",
        "example-pack.review-queue": "Fila de revisão",
        example_pack_claim: "Alegação",
        example_pack_source: "Fonte"
      }
    }
  },
  composition_sha256: "0".repeat(64)
};

function page(id: string, pageType: string, title: string): PageRecord {
  return {
    id,
    path: `memories/example/${id}.md`,
    title,
    page_type: pageType,
    context: "example",
    visibility: "public",
    status: "active",
    updated_at: "2026-07-11",
    stale_after_days: "90",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_refs: [],
    moc_parent: "",
    summary: `Summary for ${title}`
  };
}

const pages = [
  page("alpha", "example_pack_source", "Alpha Source"),
  page("beta", "example_pack_claim", "Beta Claim"),
  page("outside", "decision", "Core Decision")
];

const activeView = composition.slots.views[0];

function setup(overrides: Partial<React.ComponentProps<typeof PackWorkbench>> = {}) {
  const callbacks = {
    onSelectView: vi.fn(),
    onOpenPage: vi.fn(),
    onOpenTimeline: vi.fn(),
    onClose: vi.fn()
  };
  const result = render(
    <PackWorkbench
      composition={composition}
      requestedView={activeView.contribution}
      activeView={activeView}
      pages={pages}
      {...callbacks}
      {...overrides}
    />
  );
  return { ...result, ...callbacks };
}

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("PackWorkbench", () => {
  it("renders a generic, navigable fallback over canonical namespaced pages", () => {
    const { container, onSelectView, onOpenPage } = setup();

    expect(container.querySelector('[data-pack-id="example-pack"]')).toBeTruthy();
    expect(container.querySelectorAll("[data-pack-page-id]")).toHaveLength(2);
    expect(screen.queryByText("Core Decision")).toBeNull();
    expect(screen.getByText("Quadrant Lenses")).toBeTruthy();
    expect(container.querySelector('[data-pack-view-option="example-pack.reference-map"]')?.getAttribute("aria-current")).toBe("page");

    fireEvent.click(container.querySelector('[data-pack-view-option="example-pack.review-queue"]')!);
    expect(onSelectView).toHaveBeenCalledWith("example-pack.review-queue");

    fireEvent.click(screen.getByRole("button", { name: /Open canonical page Alpha Source/i }));
    expect(onOpenPage).toHaveBeenCalledWith("alpha");
  });

  it("renders catalog-owned PT-BR pack, contribution and page-type labels", () => {
    configureLanguage("pt-BR");
    setup();
    expect(screen.getByRole("heading", { name: "Mapa de referências" })).toBeTruthy();
    expect(screen.getByText("Conhecimento de Exemplo v1.2.3", { exact: false })).toBeTruthy();
    expect(screen.getByText("Fonte")).toBeTruthy();
    expect(screen.getByText("Alegação")).toBeTruthy();
  });

  it("keeps commands and operations discoverable but disabled, and routes temporal profiles honestly", () => {
    const { onOpenTimeline } = setup();
    const capture = screen.getByRole("button", { name: /Capture/i });
    const review = screen.getAllByRole("button", { name: /^Review/i })
      .find((button) => (button as HTMLButtonElement).disabled)!;
    expect((capture as HTMLButtonElement).disabled).toBe(true);
    expect((review as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText(/adapter/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /History/i }));
    expect(onOpenTimeline).toHaveBeenCalledWith(composition.slots.timelines[0]);
  });

  it("supports roving arrow-key navigation and text filtering", () => {
    const { onOpenPage } = setup();
    const alpha = screen.getByRole("button", { name: /Open canonical page Alpha Source/i });
    const beta = screen.getByRole("button", { name: /Open canonical page Beta Claim/i });
    alpha.focus();
    fireEvent.keyDown(alpha, { key: "ArrowRight" });
    expect(document.activeElement).toBe(beta);
    fireEvent.click(beta);
    expect(onOpenPage).toHaveBeenCalledWith("beta");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Alpha" } });
    expect(screen.getByRole("button", { name: /Open canonical page Alpha Source/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Open canonical page Beta Claim/i })).toBeNull();
  });

  it("moves focus into the shared view and lets Escape return to the native world", async () => {
    const { onClose } = setup();
    const heading = screen.getByRole("heading", { name: "Reference map" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fails closed for an unknown shared view and returns to the native world", () => {
    const { onClose } = setup({ activeView: undefined, requestedView: "unknown-pack.missing" });
    expect(screen.getByRole("alert").textContent).toContain("unknown-pack.missing");
    fireEvent.click(screen.getByRole("button", { name: /Back/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("becomes inert while the real PageReader or navigator owns the surface", () => {
    const { container } = setup({ inactive: true });
    const surface = container.querySelector<HTMLElement>(".packWorkbenchSurface")!;
    expect(surface.inert).toBe(true);
    expect(surface.getAttribute("aria-hidden")).toBe("true");
  });
});
