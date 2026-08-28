import { describe, expect, it } from "vitest";
import { foldText, rankPages, searchPages, searchTerms } from "./search";
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

  it("ranks an exact compound title above the same terms in another order", () => {
    const pages = [
      page({ id: "reordered", title: "System Wiki" }),
      page({ id: "exact", title: "Wiki System" })
    ];
    expect(rankPages(pages, "wiki system").map((p) => p.id)).toEqual(["exact", "reordered"]);
    expect(rankPages(pages, "wiki-system").map((p) => p.id)).toEqual(["exact", "reordered"]);
  });

  it("filters by type and context while exposing truthful opposite facets", () => {
    const pages = [
      page({ id: "a", title: "Finance note", page_type: "note", context: "finance" }),
      page({ id: "b", title: "Finance source", page_type: "source", context: "finance" }),
      page({ id: "c", title: "Finance source team", page_type: "source", context: "team" })
    ];
    const result = searchPages(pages, "finance", { pageType: "source", context: "finance" });
    expect(result.hits.map((p) => p.id)).toEqual(["b"]);
    expect(result.total).toBe(1);
    expect(result.pageTypes).toEqual([
      { value: "note", count: 1 },
      { value: "source", count: 1 }
    ]);
    expect(result.contexts).toEqual([
      { value: "finance", count: 1 },
      { value: "team", count: 1 }
    ]);
  });

  it("limits a scoped search to the current world's ids without changing global search", () => {
    const pages = [
      page({ id: "inside", title: "Finance inside", path: "memories/finance/inside.md" }),
      page({ id: "outside", title: "Finance outside", path: "memories/finance/outside.md" })
    ];
    expect(searchPages(pages, "finance", { allowedIds: new Set(["inside"]) }).hits.map((p) => p.id)).toEqual(["inside"]);
    expect(searchPages(pages, "finance").total).toBe(2);
  });

  it("returns nothing for an empty query", () => {
    expect(rankPages([page({ id: "a" })], "   ")).toEqual([]);
    expect(searchTerms("  ")).toEqual([]);
  });
});
