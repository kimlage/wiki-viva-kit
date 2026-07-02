import { describe, expect, it } from "vitest";
import { foldText, rankPages, searchTerms } from "./search";
import type { PageRecord } from "../types";

function page(over: Partial<PageRecord>): PageRecord {
  return {
    id: over.id || over.title || "p",
    path: "memories/x.md",
    title: "Untitled",
    page_type: "context_note",
    context: "system",
    visibility: "private_self",
    status: "",
    updated_at: "2026-07-01",
    stale_after_days: "30",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_refs: [],
    moc_parent: "",
    summary: "",
    summary_truncated: false,
    ...over
  } as PageRecord;
}

describe("search", () => {
  it("folds diacritics so accent-less queries match (PT)", () => {
    expect(foldText("Construção")).toBe("construção".normalize("NFD").replace(/[̀-ͯ]/g, ""));
    const pages = [page({ id: "a", title: "Construção da wiki" }), page({ id: "b", title: "Outra coisa" })];
    const hits = rankPages(pages, "construcao");
    expect(hits.map((p) => p.id)).toEqual(["a"]);
  });

  it("matches multiple terms across fields regardless of order/adjacency", () => {
    const pages = [
      page({ id: "hit", title: "Referência de comandos", context: "sistema", summary: "detalhes da wiki" }),
      page({ id: "miss", title: "Sistema solar", context: "outro", summary: "astronomia" })
    ];
    // "sistema" (context) + "wiki" (summary) — not adjacent, different fields.
    const hits = rankPages(pages, "sistema wiki");
    expect(hits.map((p) => p.id)).toEqual(["hit"]);
  });

  it("requires every term to hit (AND semantics)", () => {
    const pages = [page({ id: "a", title: "wiki freshness radar" })];
    expect(rankPages(pages, "wiki radar").map((p) => p.id)).toEqual(["a"]);
    expect(rankPages(pages, "wiki nonexistentterm")).toEqual([]);
  });

  it("ranks a title hit above a summary-only hit", () => {
    const pages = [
      page({ id: "summaryOnly", title: "Notes", summary: "mentions finance in passing" }),
      page({ id: "titleHit", title: "Finance overview" })
    ];
    const hits = rankPages(pages, "finance");
    expect(hits[0].id).toBe("titleHit");
    expect(hits[1].id).toBe("summaryOnly");
  });

  it("ranks exact and prefix title matches highest", () => {
    const pages = [
      page({ id: "mid", title: "the wiki system" }),
      page({ id: "prefix", title: "wiki cockpit" }),
      page({ id: "exact", title: "wiki" })
    ];
    expect(rankPages(pages, "wiki").map((p) => p.id)).toEqual(["exact", "prefix", "mid"]);
  });

  it("returns nothing for an empty query", () => {
    expect(rankPages([page({ id: "a" })], "   ")).toEqual([]);
    expect(searchTerms("  ")).toEqual([]);
  });
});
