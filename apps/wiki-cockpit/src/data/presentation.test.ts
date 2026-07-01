import { afterEach, describe, expect, it } from "vitest";
import { configurePresentation, contextStyle, edgeStyle, pageTypeLabel, pageTypeStyle, trustColor } from "./presentation";

afterEach(() => {
  configurePresentation({});
});

describe("presentation registry", () => {
  it("maps known page types to human labels and shapes", () => {
    expect(pageTypeLabel("source")).toBe("evidence source");
    expect(pageTypeStyle("decision").shape).toBe("diamond");
    expect(pageTypeStyle("action").shape).toBe("comet");
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
