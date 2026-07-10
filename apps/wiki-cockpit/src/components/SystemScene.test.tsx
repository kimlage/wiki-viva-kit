// @vitest-environment happy-dom

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { canUseWebGL, sceneMotionDurationSeconds, sceneMotionIntent, SystemScene } from "./SystemScene";
import type { SceneMotionSnapshot } from "./SystemScene";
import type { GitState, GraphNode } from "../types";

const nodes: GraphNode[] = [
  {
    id: "root",
    path: "memories/index.md",
    title: "Root",
    page_type: "root_index",
    context: "system",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 1, source_ref_count: 0 }
  },
  {
    id: "alpha",
    path: "memories/example/alpha.md",
    title: "Alpha",
    page_type: "context_note",
    context: "example",
    freshness_state: "stale",
    approved_state: "approved",
    risk_flags: [],
    updated_at: "2026-01-01",
    stale_after_days: "30",
    metrics: { inbound_links: 1, outbound_links: 0, source_ref_count: 1 }
  }
];

const git: GitState = {
  available: true,
  default_branch: "main",
  current_branch: "wiki/fallback",
  branch_prefix: "wiki/",
  worktree: { clean: true, changed_files: [] },
  upstream: { remote: "origin", ahead: 0, behind: 0, name: "", last_fetch_at: null },
  proposal: {
    is_proposal_branch: true,
    theme: "fallback",
    draft_pr_url: null,
    human_gate_state: "not_opened"
  }
};

const motionSnapshot = (patch: Partial<SceneMotionSnapshot> = {}): SceneMotionSnapshot => ({
  key: "quadrants|q2|actions||0|root|",
  view: "quadrants",
  lens: "q2",
  overlay: "actions",
  group: "",
  level: 0,
  center: "root",
  page: "",
  ...patch
});

describe("scene semantic motion transaction", () => {
  it("distinguishes view, lens, overlay and page control without a generic fallback", () => {
    const root = motionSnapshot();
    expect(sceneMotionIntent(null, root)).toBe("view");
    expect(sceneMotionIntent(root, motionSnapshot({ view: "radar" }))).toBe("view");
    expect(sceneMotionIntent(root, motionSnapshot({ lens: "q3" }))).toBe("lens");
    expect(sceneMotionIntent(root, motionSnapshot({ overlay: "evidence" }))).toBe("overlay");
    expect(sceneMotionIntent(root, motionSnapshot({ page: "page-a" }))).toBe("control");
  });

  it("uses travel for entering or recentering and retreat for reversing depth", () => {
    const root = motionSnapshot();
    const drilled = motionSnapshot({ group: "family:source", level: 2 });
    expect(sceneMotionIntent(root, drilled)).toBe("travel");
    expect(sceneMotionIntent(drilled, root)).toBe("retreat");
    expect(sceneMotionIntent(root, motionSnapshot({ center: "root-b" }))).toBe("travel");
    expect(sceneMotionIntent(motionSnapshot({ page: "page-a" }), root)).toBe("retreat");
  });

  it("keeps real overlay crossfades short and cuts them under reduced motion", () => {
    expect(sceneMotionDurationSeconds("overlay", 0.78)).toBeGreaterThanOrEqual(0.3);
    expect(sceneMotionDurationSeconds("overlay", 0.78)).toBeLessThanOrEqual(0.4);
    expect(sceneMotionDurationSeconds("overlay", 0.2)).toBe(0.4);
    expect(sceneMotionDurationSeconds("overlay", 1.4)).toBe(0.3);
    expect(sceneMotionDurationSeconds("overlay", 0.78, true)).toBe(0);
  });
});

describe("SystemScene fallback", () => {
  it("uses the 2D fallback with the same topology, URLs and measurable fallback reason", async () => {
    expect(canUseWebGL()).toBe(false);

    const { container } = render(
      <SystemScene
        nodes={nodes}
        git={git}
        route={{ perspective: "radar", reader: false, filter: "" }}
        highlightedPageIds={["alpha"]}
        makeHref={(patch) => `/w/radar${patch.context ? `/${patch.context}` : ""}`}
      />
    );

    expect(screen.getByLabelText("Content map")).toBeTruthy();
    const scene = container.querySelector(".sceneShell");
    expect(scene?.getAttribute("data-motion-intent")).toBe("view");
    expect(scene?.getAttribute("data-motion-duration-ms")).toBe("0");
    expect(screen.getByText("Draft change")).toBeTruthy();
    // Groups render as links sharing the world URL grammar.
    const groupLink = screen.getByRole("link", { name: /example · 1/ });
    expect(groupLink.getAttribute("href")).toBe("/w/radar/example");
    // Alpha is stale in the fixture: the active attention overlay resolves it
    // to a labelled/symbol-backed signal, never color alone.
    const alpha = screen.getByRole("link", { name: /Alpha Attention: Needs attention/ });
    expect(alpha.getAttribute("data-overlay")).toBe("attention");
    expect(alpha.getAttribute("data-overlay-state")).toBe("watch");
    const output = screen.getByTestId("runtime-performance") as HTMLOutputElement;
    await waitFor(() => expect(output.dataset.performanceReady).toBe("true"));
    const evidence = JSON.parse(output.value) as {
      counters: { sourceNodes: number; interactiveNodes: number; fallbackReason: string; particles: number };
      evaluations: { desktop: { normal: { status: string } } };
    };
    expect(evidence.counters).toMatchObject({
      sourceNodes: 2,
      interactiveNodes: 2,
      fallbackReason: "webgl_unavailable",
      particles: 0
    });
    expect(evidence.evaluations.desktop.normal.status).toBe("fallback");
  });
});
