// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../../data/i18n";
import type { PageRecord } from "../../types";
import { MissionCard, type MissionRow } from "./MissionCard";

const page = (id: string, title = id): PageRecord => ({
  id,
  path: `memories/demo/${id}.md`,
  title,
  page_type: "context_note",
  context: "system",
  visibility: "private_self",
  status: "",
  updated_at: "2026-07-09",
  stale_after_days: "30",
  freshness_state: "fresh",
  approved_state: "approved",
  risk_flags: [],
  source_refs: [],
  moc_parent: "",
  summary: `${title} summary`,
  summary_truncated: false
});

const rows = (onMain = vi.fn(), onAction = vi.fn()): MissionRow[] => [
  {
    key: "checks",
    label: "Run the checks",
    detail: "Five checks have not run yet.",
    help: "Checks verify the current snapshot before review.",
    tone: "warn",
    onClick: onMain
  },
  {
    key: "stale",
    label: "Update old content",
    detail: "Sixty-six pages are past their freshness window.",
    help: "Freshness identifies pages that need verification.",
    tone: "bad",
    onClick: onMain,
    action: { label: "Refresh with Codex", title: "Prepare a refresh brief", onClick: onAction }
  },
  {
    key: "browse",
    label: "Browse the world",
    detail: "Inspect the current center.",
    tone: "good",
    onClick: onMain
  }
];

const baseProps = {
  viewLabel: "Radar",
  viewHint: "Verification: what needs attention now",
  overlayLabel: "Overlay: Quality",
  missionsEnabled: true,
  open: true,
  onToggle: vi.fn(),
  query: "",
  searchHits: [] as PageRecord[],
  visibleHits: [] as PageRecord[],
  activeHit: 0,
  searchType: "",
  searchContext: "",
  searchScope: "" as const,
  searchPageTypes: [],
  searchContexts: [],
  onActiveHit: vi.fn(),
  onOpenHit: vi.fn(),
  onSearchFilter: vi.fn(),
  onShowMore: vi.fn()
};

beforeEach(() => {
  configureLanguage("en", { "world.nextSteps": "Next steps" });
});

afterEach(() => {
  cleanup();
  configureLanguage("en");
  vi.clearAllMocks();
});

describe("MissionCard", () => {
  it("uses a neutral next-steps title and explicit view, hint, and overlay context", () => {
    const { container } = render(<MissionCard {...baseProps} rows={rows()} />);

    const region = screen.getByRole("region", { name: "Next steps" });
    expect(region).toBeTruthy();
    expect(screen.getByText("Radar")).toBeTruthy();
    expect(screen.getByText("Verification: what needs attention now")).toBeTruthy();
    expect(screen.getByText("Overlay: Quality")).toBeTruthy();

    const collapse = screen.getByRole("button", { name: "–" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    expect(collapse.getAttribute("aria-controls")).toBe(region.id);
    expect(container.querySelector(".missionContextSummary")).toBeTruthy();
  });

  it("labels compatibility context instead of borrowing a native view", () => {
    const compatibilityProps = {
      ...baseProps,
      viewLabel: "Atlas",
      viewHint: "Hierarchy: what lives under each area",
      viewBadge: "Compatibility view"
    };
    const { container, rerender } = render(<MissionCard {...compatibilityProps} rows={rows()} />);

    const summary = container.querySelector(".missionContextSummary");
    expect(summary?.getAttribute("data-view-context")).toBe("compatibility");
    expect(screen.getByText("Compatibility view")).toBeTruthy();
    expect(screen.getByText("Atlas")).toBeTruthy();
    expect(screen.getByText("Hierarchy: what lives under each area")).toBeTruthy();

    rerender(<MissionCard {...compatibilityProps} rows={rows()} open={false} />);
    const chip = screen.getByRole("button", { name: /Compatibility view.*Atlas.*2 pending/ });
    expect(chip.getAttribute("data-view-context")).toBe("compatibility");
  });

  it("keeps secondary CTA and help in a separate action band", () => {
    const onMain = vi.fn();
    const onAction = vi.fn();
    const { container } = render(<MissionCard {...baseProps} rows={rows(onMain, onAction)} />);

    const main = screen.getByRole("button", { name: /Update old content/ });
    const action = screen.getByRole("button", { name: "Refresh with Codex" });
    const band = screen.getByRole("group", { name: "Update old content" });

    expect(band.classList.contains("missionRowActions")).toBe(true);
    expect((band as HTMLElement).style.flexBasis).toBe("100%");
    expect(band.contains(main)).toBe(false);
    expect(band.contains(action)).toBe(true);
    expect(band.querySelector(".helpTipButton")).toBeTruthy();
    expect(container.querySelector(".missionRowMain")?.parentElement?.classList.contains("missionRow")).toBe(true);

    fireEvent.click(main);
    fireEvent.click(action);
    expect(onMain).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("keeps a read-only secondary CTA visible but natively inert", () => {
    const onAction = vi.fn();
    const demoRows = rows(vi.fn(), onAction);
    demoRows[1] = {
      ...demoRows[1],
      action: {
        ...demoRows[1].action!,
        disabled: true,
        title: "Read-only demo: this control is disabled and sends nothing to the local operator."
      }
    };
    render(<MissionCard {...baseProps} rows={demoRows} />);

    const action = screen.getByRole("button", { name: /Refresh with Codex.*Read-only demo/i });
    expect((action as HTMLButtonElement).disabled).toBe(true);
    expect(action.getAttribute("title")).toMatch(/sends nothing/i);
    fireEvent.click(action);
    expect(onAction).not.toHaveBeenCalled();
  });

  it("collapses to the current view plus actionable pending count", () => {
    const onToggle = vi.fn();
    render(<MissionCard {...baseProps} rows={rows()} open={false} onToggle={onToggle} />);

    const chip = screen.getByRole("button", { name: /Radar.*2 pending/ });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    expect(chip.getAttribute("aria-controls")).toBeTruthy();
    expect(chip.getAttribute("title")).toBe("Verification: what needs attention now · Overlay: Quality");
    expect(chip.classList.contains("tone-bad")).toBe(true);

    fireEvent.click(chip);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("preserves search when missions are disabled", () => {
    const alpha = page("alpha", "Alpha result");
    const onActiveHit = vi.fn();
    const onOpenHit = vi.fn();
    render(
      <MissionCard
        {...baseProps}
        rows={[]}
        missionsEnabled={false}
        query="alpha"
        searchHits={[alpha]}
        visibleHits={[alpha]}
        onActiveHit={onActiveHit}
        onOpenHit={onOpenHit}
      />
    );

    expect(screen.queryByText("Next steps")).toBeNull();
    const result = screen.getByRole("option", { name: /Alpha result/ });
    fireEvent.pointerMove(result);
    fireEvent.click(result);
    expect(onActiveHit).toHaveBeenCalledWith(0);
    expect(onOpenHit).toHaveBeenCalledWith(alpha);
  });

  it("exposes typed facets, current-world scope, listbox selection and explicit disclosure", () => {
    const hits = Array.from({ length: 12 }, (_, index) => page(`p-${index}`, `Result ${index + 1}`));
    const onSearchFilter = vi.fn();
    const onShowMore = vi.fn();
    render(
      <MissionCard
        {...baseProps}
        rows={[]}
        missionsEnabled={false}
        query="result"
        searchHits={hits}
        visibleHits={hits.slice(0, 10)}
        activeHit={1}
        searchPageTypes={[{ value: "context_note", count: 12 }]}
        searchContexts={[{ value: "system", count: 12 }]}
        onSearchFilter={onSearchFilter}
        onShowMore={onShowMore}
      />
    );

    const listbox = screen.getByRole("listbox", { name: /12 result/ });
    expect(listbox.querySelectorAll('[role="option"]')[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.change(screen.getByRole("combobox", { name: "Type" }), { target: { value: "context_note" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Scope" }), { target: { value: "world" } });
    fireEvent.click(screen.getByRole("button", { name: /Show 2 more.*2 remaining/ }));

    expect(onSearchFilter).toHaveBeenNthCalledWith(1, { searchType: "context_note" });
    expect(onSearchFilter).toHaveBeenNthCalledWith(2, { searchScope: "world" });
    expect(onShowMore).toHaveBeenCalledTimes(1);
  });
});
