import { describe, expect, it } from "vitest";
import type { GraphNode, OverlayMetrics } from "../types";
import { __dictKeysForTest, configureLanguage } from "./i18n";
import {
  aggregateOverlayMetrics,
  localizedEncodingAria,
  localizedEncodingText,
  SEMANTIC_VISUAL_TOKENS,
  SEMANTIC_VISUAL_TOKENS_VERSION,
  STRONG_ATTENTION_MARK_BUDGET,
  strongAttentionNodeIds,
  visualEncodingResolver
} from "./visualEncoding";

const metrics: OverlayMetrics = {
  attention: { state: "urgent", value: 1, count: 2, reasons: ["gate:fail"], refs: ["gate:honesty"] },
  freshness: { state: "stale", value: 0, count: 1, reasons: ["freshness:stale"], refs: [] },
  actions: { state: "blocked", value: 1, count: 1, reasons: ["action:blocked"], refs: ["action:fix"] },
  ownership: { state: "assigned", value: 1, count: 1, reasons: ["owner:recorded"], refs: ["person:bea"] },
  evidence: { state: "linked", value: 1, count: 3, reasons: ["source_refs"], refs: ["source:a"] },
  quality: { state: "flagged", value: 2, count: 2, reasons: ["missing_link", "bad_frontmatter"], refs: [] }
};

const node = (context: string, overlay_metrics: OverlayMetrics = metrics): GraphNode => ({
  id: `node-${context}`,
  path: `memories/${context}.md`,
  title: context,
  page_type: "action",
  context,
  freshness_state: "stale",
  approved_state: "approved",
  risk_flags: ["gate_fail"],
  metrics: { inbound_links: 1, outbound_links: 2, source_ref_count: 3 },
  overlay_metrics
});

describe("VisualEncodingResolver v1", () => {
  it("resolves every v8 overlay from data with a redundant symbol and text", () => {
    expect(visualEncodingResolver.version).toBe(SEMANTIC_VISUAL_TOKENS_VERSION);
    for (const overlay of ["attention", "freshness", "actions", "ownership", "evidence", "quality"] as const) {
      const resolved = visualEncodingResolver.resolve(node("finance"), overlay);
      expect(resolved.dataBacked).toBe(true);
      expect(resolved.symbol.length).toBeGreaterThan(0);
      expect(resolved.valueText.length).toBeGreaterThan(0);
      expect(resolved.accessibleText).toContain(resolved.overlayLabel);
      expect(resolved.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("uses active-overlay data rather than context hue", () => {
    const first = visualEncodingResolver.resolve(node("finance"), "attention");
    const second = visualEncodingResolver.resolve(node("people"), "attention");
    expect(first.color).toBe(second.color);
    expect(first.symbol).toBe(second.symbol);
    expect(first.state).toBe("urgent");
  });

  it("changes encoding without touching identity or spatial coordinates", () => {
    const spatial = { id: "page-a", position: [1.25, 0, -3.5] as const };
    const before = JSON.stringify(spatial);
    const encodings = ["attention", "freshness", "actions", "ownership", "evidence", "quality"].map((overlay) =>
      visualEncodingResolver.resolve(node("system"), overlay as keyof OverlayMetrics)
    );
    expect(new Set(encodings.map((encoding) => encoding.color)).size).toBeGreaterThan(3);
    expect(JSON.stringify(spatial)).toBe(before);
  });

  it("aggregates group state from real member metrics", () => {
    const calm = structuredClone(metrics);
    calm.attention = { state: "quiet", value: 0, count: 0, reasons: [], refs: [] };
    calm.actions = { state: "none", value: 0, count: 0, reasons: [], refs: [] };
    const aggregate = aggregateOverlayMetrics([node("finance"), node("people", calm)]);
    expect(aggregate.attention.state).toBe("urgent");
    expect(aggregate.actions.count).toBe(1);
    expect(aggregate.evidence.count).toBe(6);
    expect(aggregate.ownership.refs).toEqual(["person:bea"]);
  });

  it("marks legacy snapshots as compatibility-derived instead of fabricating source truth", () => {
    const legacy = node("system");
    delete legacy.overlay_metrics;
    const resolved = visualEncodingResolver.resolve(legacy, "freshness");
    expect(resolved.dataBacked).toBe(false);
    expect(resolved.state).toBe("stale");
    expect(resolved.accessibleText).toContain("Freshness");
  });

  it("ships EN/PT labels and aria text for every overlay state, including cancelled", () => {
    const en = new Set(__dictKeysForTest.en);
    const pt = new Set(__dictKeysForTest.pt);
    for (const [overlay, scale] of Object.entries(SEMANTIC_VISUAL_TOKENS)) {
      for (const state of Object.keys(scale.states)) {
        const key = `overlay.state.${overlay}.${state}`;
        expect(en.has(key), `missing EN ${key}`).toBe(true);
        expect(pt.has(key), `missing PT ${key}`).toBe(true);
      }
    }

    const cancelled = structuredClone(metrics);
    cancelled.actions = { state: "cancelled", value: 0, count: 1, reasons: ["action:cancelled"], refs: ["action:x"] };
    const encoding = visualEncodingResolver.resolve(node("system", cancelled), "actions");
    try {
      configureLanguage("pt-BR");
      expect(localizedEncodingText(encoding)).toBe("Ação cancelada · 1");
      expect(localizedEncodingAria(encoding)).toBe("Ações: Ação cancelada · 1");
      expect(localizedEncodingAria(encoding)).not.toContain("overlay.state");
      configureLanguage("en");
      expect(localizedEncodingText(encoding)).toBe("Cancelled action · 1");
      expect(localizedEncodingAria(encoding)).toBe("Actions: Cancelled action · 1");
    } finally {
      configureLanguage("en");
    }
  });

  it("caps strong attention marks deterministically while preserving all node data", () => {
    const crowded = Array.from({ length: 20 }, (_, index) => {
      const itemMetrics = structuredClone(metrics);
      itemMetrics.attention = {
        state: index < 4 ? "urgent" : "watch",
        value: index < 4 ? 1 : 0.5,
        count: 20 - index,
        reasons: [`signal:${index}`],
        refs: []
      };
      return { ...node(`context-${index}`, itemMetrics), id: `node-${String(index).padStart(2, "0")}` };
    });
    const first = strongAttentionNodeIds(crowded);
    const second = strongAttentionNodeIds([...crowded].reverse());
    expect(first.size).toBe(STRONG_ATTENTION_MARK_BUDGET);
    expect([...first]).toEqual([...second]);
    expect([...first].slice(0, 4)).toEqual(["node-00", "node-01", "node-02", "node-03"]);
    expect(crowded).toHaveLength(20);
  });

  it("keeps never-synced sources distinct from unknown freshness", () => {
    const sourceMetrics = structuredClone(metrics);
    sourceMetrics.freshness = {
      state: "never_synced",
      value: 0,
      count: 1,
      reasons: ["source_lifecycle:never_synced"],
      refs: ["source:crm"]
    };
    const encoding = visualEncodingResolver.resolve(node("sources", sourceMetrics), "freshness");
    expect(encoding.state).toBe("never_synced");
    expect(encoding.symbol).toBe("∅");
    expect(encoding.ring).toBe("dashed");
    try {
      configureLanguage("pt-BR");
      expect(localizedEncodingText(encoding)).toBe("Nunca sincronizada · 1");
    } finally {
      configureLanguage("en");
    }
  });
});
