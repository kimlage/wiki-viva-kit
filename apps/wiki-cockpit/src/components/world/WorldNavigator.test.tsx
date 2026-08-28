// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorldNavigator } from "./WorldNavigator";
import type { CompatibilityViewContext } from "./WorldNavigator";
import type { NativeWorldViewId } from "../../world/experience";
import type { ExperiencePackComposition } from "../../types";

const COPY: Record<string, string> = {
  "world.experience.compactAria": "World view controls",
  "world.experience.viewGroupAria": "Arrange the same pages",
  "world.experience.compatibility.badge": "Compatibility view",
  "world.experience.compatibility.switchHint": "Choose a native view to continue.",
  "world.overlayControl": "Overlay",
  "world.experience.learn": "Learn how this works",
  "world.experience.close": "Close explanation",
  "world.experience.title": "Understand this world",
  "world.experience.intro": "Three independent choices shape the reading.",
  "world.experience.mentalModel.title": "The mental model",
  "world.experience.views.title": "Choose an arrangement",
  "world.experience.views.intro": "A view moves the same pages without changing their identity.",
  "world.experience.overlays.title": "Choose a signal",
  "world.experience.overlays.intro": "An overlay changes visual encoding without moving pages.",
  "world.experience.lenses.title": "Choose a quadrant lens",
  "world.experience.lenses.intro": "A lens scopes the current center and works in every view.",
  "world.view.quadrants": "Quadrants",
  "world.view.radar": "Radar",
  "world.view.sources": "Sources",
  "world.view.work": "Work",
  "world.view.timeline": "Timeline",
  "world.overlay.attention": "Attention",
  "world.overlay.freshness": "Freshness",
  "world.overlay.actions": "Actions",
  "world.overlay.ownership": "Ownership",
  "world.overlay.evidence": "Evidence",
  "world.overlay.quality": "Quality",
  "world.experience.lens.all.label": "All",
  "world.experience.lens.q1.label": "Q1 · Intention",
  "world.experience.lens.q2.label": "Q2 · Practice",
  "world.experience.lens.q3.label": "Q3 · Relations",
  "world.experience.lens.q4.label": "Q4 · Systems",
  "world.experience.capability.spatialOnly": "Spatial controls are paused.",
  "world.experience.capability.timelineUnavailable": "Timeline unavailable.",
  "world.experience.packs.short": "Extensions",
  "world.experience.packs.title": "Experience packs",
  "world.experience.packs.intro": "Composed slots.",
  "world.experience.packs.active": "Active packs",
  "world.experience.packs.coreOnly": "Core only",
  "world.experience.packs.slot.views": "Views",
  "world.experience.packs.slot.commands": "Commands",
  "world.experience.packs.slot.operations": "Operations",
  "world.experience.packs.slot.timelines": "Temporal profiles",
  "world.experience.packs.slot.empty": "No contribution",
  "world.experience.packs.blockPackages": "Composed block packages",
  "world.experience.packs.openView": "Open extension view"
};

const experiencePacks: ExperiencePackComposition = {
  schema_version: "wiki_experience_pack_composition.v1",
  core_version: "8.0.0",
  packs: [{ id: "study-research", version: "0.1.0" }],
  block_packages: ["quadrant_lenses"],
  slots: {
    views: [{ pack: "study-research", slot: "view.knowledge", contribution: "study-research.concept-graph", mode: "append" }],
    commands: [{ pack: "study-research", slot: "command.capture", contribution: "study-research.capture", mode: "append" }],
    operations: [{ pack: "study-research", slot: "operation.review", contribution: "study-research.review-evidence", mode: "append" }],
    timelines: [{ pack: "study-research", slot: "timeline.history", contribution: "study-research.learning-history", mode: "append" }]
  },
  presentation: {
    default_locale: "en",
    locales: {
      en: {
        "study-research": "Study and Research",
        "study-research.capture": "Capture",
        "study-research.concept-graph": "Concept graph",
        "study-research.learning-history": "Learning history",
        "study-research.review-evidence": "Review evidence"
      },
      "pt-BR": {
        "study-research": "Estudos e pesquisa",
        "study-research.capture": "Capturar",
        "study-research.concept-graph": "Grafo de conceitos",
        "study-research.learning-history": "Histórico de aprendizagem",
        "study-research.review-evidence": "Revisar evidências"
      }
    }
  },
  composition_sha256: "0".repeat(64)
};

function translate(key: string): string {
  return COPY[key] ?? `translated:${key}`;
}

function setup(options: {
  expanded?: boolean;
  lens?: "q1_intencao" | "q2_pratica" | "q3_relacoes" | "q4_sistemas" | "type" | null;
  view?: NativeWorldViewId | null;
  compatibilityView?: CompatibilityViewContext;
  experiencePacks?: ExperiencePackComposition;
  temporalUnavailable?: boolean;
} = {}) {
  const callbacks = {
    onExpandedChange: vi.fn(),
    onViewChange: vi.fn(),
    onOverlayChange: vi.fn(),
    onLensChange: vi.fn(),
    onPackViewChange: vi.fn()
  };
  const result = render(
    <WorldNavigator
      view={options.view === undefined ? "radar" : options.view}
      compatibilityView={options.compatibilityView}
      experiencePacks={options.experiencePacks}
      unavailableViews={options.temporalUnavailable ? ["timeline"] : []}
      lensAvailable={!options.temporalUnavailable}
      overlayAvailable={!options.temporalUnavailable}
      overlay="freshness"
      lens={options.lens ?? "type"}
      expanded={options.expanded}
      panelId="experience-test"
      translate={translate}
      {...callbacks}
    />
  );
  return { ...result, ...callbacks };
}

afterEach(cleanup);

describe("WorldNavigator", () => {
  it("renders a compact five-view control, six-option overlay select and learn button", () => {
    const { container, onViewChange, onOverlayChange } = setup();

    expect(container.querySelectorAll("[data-view-option]")).toHaveLength(5);
    expect(screen.getByRole("group", { name: "Arrange the same pages" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Radar" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("combobox", { name: "Overlay" }).querySelectorAll("option")).toHaveLength(6);

    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(onViewChange).toHaveBeenCalledWith("sources");

    fireEvent.change(screen.getByRole("combobox", { name: "Overlay" }), { target: { value: "quality" } });
    expect(onOverlayChange).toHaveBeenCalledWith("quality");

    const learn = screen.getByRole("button", { name: "Learn how this works" });
    expect(learn.getAttribute("aria-expanded")).toBe("false");
    expect(learn.getAttribute("aria-controls")).toBe("experience-test");
  });

  it("shows an honest compatibility context without pressing a native view", () => {
    const compatibilityView = {
      id: "atlas",
      label: "Atlas",
      hint: "Hierarchy: what lives under each area"
    };
    const { container, onViewChange } = setup({ view: null, compatibilityView, expanded: true });

    expect(container.querySelector(".worldNavigator")?.getAttribute("data-native-view")).toBe("");
    expect(container.querySelector(".worldNavigator")?.getAttribute("data-compatibility-view")).toBe("atlas");
    expect(screen.getByRole("note", { name: /Compatibility view: Atlas/ })).toBeTruthy();
    expect(container.querySelector('[data-compatibility-notice="atlas"]')).toBeTruthy();
    expect(container.querySelectorAll('[data-view-option][aria-pressed="true"]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-view-card][aria-pressed="true"]')).toHaveLength(0);
    expect(screen.getAllByText("Hierarchy: what lives under each area").length).toBeGreaterThanOrEqual(1);

    fireEvent.click(container.querySelector('[data-view-option="quadrants"]')!);
    expect(onViewChange).toHaveBeenCalledWith("quadrants");
  });

  it("expands into an explained three-axis model with all cards and lenses", () => {
    const { container } = setup({ expanded: true, lens: "q2_pratica" });

    expect(screen.getByRole("region", { name: "Understand this world" })).toBeTruthy();
    expect(container.querySelectorAll("[data-experience-axis]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-experience-section]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-view-card]")).toHaveLength(5);
    expect(container.querySelectorAll("[data-overlay-card]")).toHaveLength(6);
    expect(container.querySelectorAll("[data-lens-option]")).toHaveLength(5);
    expect(container.querySelector('[data-lens-option="q2_pratica"]')?.getAttribute("aria-pressed")).toBe("true");

    for (const card of container.querySelectorAll<HTMLElement>("[data-view-card], [data-overlay-card], [data-lens-option]")) {
      const describedBy = card.getAttribute("aria-describedby");
      expect(describedBy).toBeTruthy();
      expect(describedBy ? document.getElementById(describedBy) : null).toBeTruthy();
    }
  });

  it("dispatches expanded view, overlay and quadrant-lens choices without conflating them", () => {
    const { container, onViewChange, onOverlayChange, onLensChange } = setup({ expanded: true });

    fireEvent.click(container.querySelector('[data-view-card="work"]')!);
    fireEvent.click(container.querySelector('[data-overlay-card="ownership"]')!);
    fireEvent.click(container.querySelector('[data-lens-option="q3_relacoes"]')!);
    fireEvent.click(container.querySelector('[data-lens-option="all"]')!);

    expect(onViewChange).toHaveBeenCalledWith("work");
    expect(onOverlayChange).toHaveBeenCalledWith("ownership");
    expect(onLensChange).toHaveBeenNthCalledWith(1, "q3_relacoes");
    expect(onLensChange).toHaveBeenNthCalledWith(2, "all");
  });

  it("keeps an overlay resolve atomic before accepting another signal", () => {
    const callbacks = {
      onExpandedChange: vi.fn(),
      onViewChange: vi.fn(),
      onOverlayChange: vi.fn(),
      onLensChange: vi.fn()
    };
    const { container } = render(
      <WorldNavigator
        view="radar"
        overlay="actions"
        overlayResolving
        expanded
        panelId="resolving-overlay"
        translate={translate}
        {...callbacks}
      />
    );

    expect(screen.getByRole("combobox", { name: "Overlay" }).hasAttribute("disabled")).toBe(true);
    expect(container.querySelectorAll<HTMLButtonElement>("[data-overlay-card]:disabled")).toHaveLength(6);
    fireEvent.click(container.querySelector('[data-overlay-card="quality"]')!);
    expect(callbacks.onOverlayChange).not.toHaveBeenCalled();
  });

  it("disables unavailable or spatial-only controls without leaving false affordances", () => {
    const { container } = setup({ temporalUnavailable: true, expanded: true });
    expect((container.querySelector('[data-view-option="timeline"]') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "Overlay" }) as HTMLSelectElement).disabled).toBe(true);
    expect(container.querySelectorAll<HTMLButtonElement>("[data-lens-option]:disabled")).toHaveLength(5);
    expect(screen.getAllByRole("note").some((note) => note.textContent?.includes("Spatial controls are paused"))).toBe(true);
    expect(container.querySelector('[data-view-option="timeline"]')?.getAttribute("aria-describedby")).toContain("unavailable-views");
  });

  it("renders installed packs and every composed slot as an honest catalog", () => {
    const { container, onPackViewChange } = setup({ expanded: true, experiencePacks });
    expect(container.querySelectorAll("[data-experience-section]")).toHaveLength(4);
    expect(container.querySelector('[data-experience-section="packs"]')).toBeTruthy();
    expect(container.querySelector('[data-active-pack-count="1"]')).toBeTruthy();
    expect(container.querySelector('[data-pack-id="study-research"]')).toBeTruthy();
    expect(container.querySelectorAll("[data-pack-slot-kind]")).toHaveLength(4);
    expect(screen.getByLabelText("Composed block packages").textContent).toContain("quadrant_lenses");
    expect(screen.getByText("study-research.concept-graph")).toBeTruthy();
    expect(screen.getByText("study-research.review-evidence")).toBeTruthy();
    expect(screen.getByText("study-research.learning-history")).toBeTruthy();
    const packView = container.querySelector<HTMLButtonElement>('[data-pack-view-card="study-research.concept-graph"]')!;
    expect(packView.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(packView);
    expect(onPackViewChange).toHaveBeenCalledWith("study-research.concept-graph");
  });

  it("supports controlled explanation state, reports explicit close and restores focus", async () => {
    const { container, onExpandedChange, rerender } = setup({ expanded: true });
    const learn = screen.getByRole("button", { name: "Learn how this works" });
    expect(learn.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Close explanation" }));
    expect(onExpandedChange).toHaveBeenCalledWith(false);
    rerender(
      <WorldNavigator
        view="radar"
        overlay="freshness"
        lens="type"
        expanded={false}
        panelId="experience-test"
        translate={translate}
        onExpandedChange={onExpandedChange}
        onViewChange={vi.fn()}
        onOverlayChange={vi.fn()}
        onLensChange={vi.fn()}
      />
    );
    const closing = container.querySelector<HTMLElement>(".worldNavigatorPanel.closing");
    expect(closing?.dataset.surfacePhase).toBe("closing");
    expect(screen.queryByRole("region", { name: "Understand this world" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(learn));
  });

  it("supports an uncontrolled learn flow and closes the contextual panel with Escape", async () => {
    const onExpandedChange = vi.fn();
    render(
      <WorldNavigator
        view="quadrants"
        overlay="actions"
        lens={null}
        panelId="uncontrolled-experience"
        translate={translate}
        onExpandedChange={onExpandedChange}
        onViewChange={vi.fn()}
        onOverlayChange={vi.fn()}
        onLensChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Learn how this works" }));
    const panel = screen.getByRole("region", { name: "Understand this world" });
    expect(panel).toBeTruthy();
    expect(onExpandedChange).toHaveBeenLastCalledWith(true);

    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Understand this world" })).toBeNull();
    expect(onExpandedChange).toHaveBeenLastCalledWith(false);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Learn how this works" })));
  });
});
