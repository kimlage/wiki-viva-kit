import { afterEach, describe, expect, it } from "vitest";
import {
  agedColor,
  configurePresentation,
  contextStyle,
  edgeStyle,
  hexToOklch,
  pageTypeLabel,
  pageTypeStyle,
  registerContextPalette,
  trustColor
} from "./presentation";

afterEach(() => {
  configurePresentation({});
  registerContextPalette([]);
});

// --- CVD simulation (Viénot 1999 dichromat matrices over linear sRGB) -------
// Small on purpose: enough to keep the palette honest for protan/deutan users.
function hexToLinearRgb(hex: string): [number, number, number] {
  const int = parseInt(hex.slice(1), 16);
  const channel = (value: number) => {
    const v = value / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return [channel((int >> 16) & 255), channel((int >> 8) & 255), channel(int & 255)];
}
function simulateDichromat(hex: string, kind: "protan" | "deutan"): [number, number, number] {
  const [r, g, b] = hexToLinearRgb(hex);
  // Viénot/Brettel/Mollon reduction matrices (linear RGB in/out).
  return kind === "protan"
    ? [0.11238 * r + 0.88762 * g, 0.11238 * r + 0.88762 * g, 0.004 * r - 0.004 * g + 1 * b]
    : [0.29275 * r + 0.70725 * g, 0.29275 * r + 0.70725 * g, -0.02234 * r + 0.02234 * g + 1 * b];
}
// Perceptual-ish distance on simulated linear RGB (weighted Euclidean ×100).
function simDistance(a: string, b: string, kind: "protan" | "deutan"): number {
  const [r1, g1, b1] = simulateDichromat(a, kind);
  const [r2, g2, b2] = simulateDichromat(b, kind);
  return Math.sqrt(2 * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + 3 * (b1 - b2) ** 2) * 100;
}

describe("presentation registry", () => {
  it("maps known page types to human labels and shapes", () => {
    expect(pageTypeLabel("source")).toBe("evidence source");
    expect(pageTypeStyle("decision").shape).toBe("diamond");
    expect(pageTypeStyle("action").shape).toBe("comet");
    expect(pageTypeStyle("meeting").shape).toBe("spark");
    expect(pageTypeStyle("operational_rule").shape).toBe("slab");
    expect(pageTypeStyle("person").shape).toBe("totem");
    expect(pageTypeStyle("context_hub").family).toBe("hub");
  });

  it("degrades unknown localized page types to readable defaults", () => {
    const style = pageTypeStyle("nota_de_campo");
    expect(style.label).toBe("nota de campo");
    expect(style.shape).toBe("sphere");
    expect(style.family).toBe("content");
  });

  it("applies runtime overrides for page types, contexts and trust colors", () => {
    configurePresentation({
      page_types: { claim: { label: "hipótese", shape: "spark" } },
      contexts: { financeiro: { label: "Finanças", accent: "#123456" } },
      trust_colors: { stale: "#ff0000" }
    });
    expect(pageTypeLabel("claim")).toBe("hipótese");
    expect(pageTypeStyle("claim").shape).toBe("spark");
    expect(contextStyle("financeiro")).toEqual({ label: "Finanças", accent: "#123456" });
    expect(trustColor("stale")).toBe("#ff0000");
    expect(trustColor("fresh")).toBe("#5ee6a8");
  });

  it("keeps context accents deterministic without overrides", () => {
    expect(contextStyle("finance").accent).toBe(contextStyle("finance").accent);
    expect(contextStyle("").label).toBe("system");
  });

  it("styles graph edge types with stable labels", () => {
    expect(edgeStyle("moc_parent").label).toBe("navigation");
    expect(edgeStyle("source_ref").label).toBe("evidence");
    expect(edgeStyle("custom_edge").label).toBe("custom edge");
  });
});

describe("context secondary-keyline palette registry", () => {
  const PRIVATE_LIKE = ["financeiro", "sistema", "empresas", "profissional", "documentos", "fiscal", "projetos-pessoais", "custos"];

  it("assigns 8 registered contexts 8 DISTINCT accents (sorted, deterministic)", () => {
    registerContextPalette(PRIVATE_LIKE);
    const accents = PRIVATE_LIKE.map((name) => contextStyle(name).accent);
    expect(new Set(accents).size).toBe(8);
    // Deterministic: registering again in another order changes nothing.
    registerContextPalette([...PRIVATE_LIKE].reverse());
    expect(PRIVATE_LIKE.map((name) => contextStyle(name).accent)).toEqual(accents);
  });

  it("never hands a context a reserved state accent", () => {
    registerContextPalette(PRIVATE_LIKE);
    const reserved = [trustColor("stale"), trustColor("proposal"), trustColor("risk"), trustColor("fresh")];
    for (const name of PRIVATE_LIKE) {
      expect(reserved).not.toContain(contextStyle(name).accent);
    }
  });

  it("keeps 8 registered accents distinguishable under protan AND deutan simulation", () => {
    registerContextPalette(PRIVATE_LIKE);
    const accents = PRIVATE_LIKE.map((name) => contextStyle(name).accent);
    for (let i = 0; i < accents.length; i += 1) {
      for (let j = i + 1; j < accents.length; j += 1) {
        expect(simDistance(accents[i], accents[j], "protan"), `${accents[i]} vs ${accents[j]} protan`).toBeGreaterThan(8);
        expect(simDistance(accents[i], accents[j], "deutan"), `${accents[i]} vs ${accents[j]} deutan`).toBeGreaterThan(8);
      }
    }
  });
});

describe("agedColor (tone = state, lightness bands)", () => {
  const CONTEXTS = ["financeiro", "sistema", "empresas", "profissional", "documentos", "fiscal", "projetos-pessoais", "custos"];

  it("holds the cross-context lightness ordering: proposal > fresh > stale > unknown", () => {
    registerContextPalette(CONTEXTS);
    const bands = { proposal: [] as number[], fresh: [] as number[], stale: [] as number[], unknown: [] as number[] };
    for (const name of CONTEXTS) {
      const accent = contextStyle(name).accent;
      bands.proposal.push(hexToOklch(agedColor(accent, "proposal")).l);
      bands.fresh.push(hexToOklch(agedColor(accent, "fresh")).l);
      bands.stale.push(hexToOklch(agedColor(accent, "stale")).l);
      bands.unknown.push(hexToOklch(agedColor(accent, "unknown")).l);
    }
    // The DARKEST proposal is lighter than the LIGHTEST fresh, and so on —
    // "darker = staler" holds across every context, the channel dichromats
    // (and the minimap) can always trust.
    expect(Math.min(...bands.proposal)).toBeGreaterThan(Math.max(...bands.fresh) + 0.1);
    expect(Math.min(...bands.fresh)).toBeGreaterThan(Math.max(...bands.stale) + 0.08);
    expect(Math.min(...bands.stale)).toBeGreaterThan(Math.max(...bands.unknown) + 0.08);
  });

  it("keeps the hue family readable in the fresh and proposal bands", () => {
    const accent = "#6ca1e5"; // blue slot
    const fresh = hexToOklch(agedColor(accent, "fresh"));
    const proposal = hexToOklch(agedColor(accent, "proposal"));
    const source = hexToOklch(accent);
    const hueDelta = (a: number, b: number) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b));
    expect(hueDelta(fresh.h, source.h)).toBeLessThan(15);
    expect(hueDelta(proposal.h, source.h)).toBeLessThan(15);
    expect(proposal.c).toBeGreaterThanOrEqual(0.045); // bleached, never pure white
  });

  it("is deterministic and memo-safe", () => {
    expect(agedColor("#4cb58c", "stale")).toBe(agedColor("#4cb58c", "stale"));
  });
});
