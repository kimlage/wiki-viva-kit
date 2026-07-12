// Ranked, accent-folded, multi-term page search. The old matcher was a single
// contiguous-substring test over joined fields in array order, capped at 8 —
// which fails badly at real scale: "sistema wiki" matched only pages where those
// two words happen to be adjacent, and a PT operator typing "construcao" (no
// cedilla) found almost nothing. This module fixes all three:
//   * fold — strip diacritics so "construcao" matches "construção".
//   * tokenize — every term must match SOMEWHERE (AND across fields), so word
//     order and separation stop mattering.
//   * rank — a term hitting the title outranks one hitting only the summary;
//     exact/prefix/word-boundary hits outrank a mid-word substring.
// Pure and deterministic → unit-testable without the 3D scene.

import type { PageRecord } from "../types";

export type SearchFacet = { value: string; count: number };

export type SearchOptions = {
  pageType?: string;
  context?: string;
  allowedIds?: ReadonlySet<string>;
};

export type SearchResult = {
  hits: PageRecord[];
  total: number;
  pageTypes: SearchFacet[];
  contexts: SearchFacet[];
};

export function foldText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

function wordBoundaryHit(haystack: string, term: string): boolean {
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(term, from);
    if (at === -1) return false;
    const before = at === 0 ? " " : haystack[at - 1];
    if (!/[a-z0-9]/.test(before)) return true;
    from = at + 1;
  }
}

// Score one term against one page's fields; 0 means "no hit for this term".
function scoreTerm(fields: { title: string; context: string; type: string; path: string; summary: string; refs: string }, term: string): number {
  const { title, context, type, path, summary, refs } = fields;
  if (title === term) return 100;
  if (title.startsWith(term)) return 62;
  if (wordBoundaryHit(title, term)) return 46;
  if (title.includes(term)) return 30;
  if (wordBoundaryHit(context, term) || wordBoundaryHit(type, term)) return 22;
  if (context.includes(term) || type.includes(term)) return 16;
  if (wordBoundaryHit(path, term)) return 14;
  if (path.includes(term)) return 10;
  if (wordBoundaryHit(summary, term)) return 9;
  if (summary.includes(term)) return 6;
  if (refs.includes(term)) return 4;
  return 0;
}

export function searchTerms(query: string): string[] {
  return foldText(query).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

function stableCompare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function facetCounts(pages: readonly PageRecord[], field: "page_type" | "context"): SearchFacet[] {
  const counts = new Map<string, number>();
  for (const page of pages) {
    const value = page[field] || "";
    if (!value) continue;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || stableCompare(foldText(a.value), foldText(b.value)) || stableCompare(a.value, b.value));
}

/** Search with independent typed facets. Facet counts are calculated after
 *  the query/scope and the opposite facet, so choosing a type keeps the
 *  context choices truthful (and vice versa). */
export function searchPages(pages: PageRecord[], query: string, options: SearchOptions = {}): SearchResult {
  const terms = searchTerms(query);
  if (!terms.length) return { hits: [], total: 0, pageTypes: [], contexts: [] };
  const normalizedQuery = terms.join(" ");
  const scored: { page: PageRecord; score: number; titleKey: string }[] = [];
  for (const page of pages) {
    if (options.allowedIds && !options.allowedIds.has(page.id) && !options.allowedIds.has(page.path)) continue;
    const fields = {
      title: foldText(page.title || ""),
      context: foldText(page.context || ""),
      type: foldText(page.page_type || ""),
      path: foldText(page.path || ""),
      summary: foldText(page.summary || ""),
      refs: foldText((page.source_refs || []).join(" "))
    };
    let total = 0;
    let matchedAll = true;
    for (const term of terms) {
      const termScore = scoreTerm(fields, term);
      if (termScore === 0) {
        matchedAll = false;
        break;
      }
      total += termScore;
    }
    if (!matchedAll) continue;

    // Full-title intent must win before term-level relevance. Without this
    // tier, "wiki system" tied "Wiki System" and "System Wiki" and the
    // alphabetical fallback could place the reordered title first.
    const normalizedTitle = searchTerms(page.title || "").join(" ");
    const titleTier = normalizedTitle === normalizedQuery
      ? 4
      : normalizedTitle.startsWith(normalizedQuery)
        ? 3
        : terms.every((term) => fields.title.includes(term))
          ? 2
          : terms.some((term) => fields.title.includes(term))
            ? 1
            : 0;
    scored.push({ page, score: titleTier * 10_000 + total, titleKey: fields.title });
  }
  scored.sort((a, b) =>
    b.score - a.score ||
    stableCompare(a.titleKey, b.titleKey) ||
    stableCompare(a.page.id, b.page.id)
  );

  const candidates = scored.map((entry) => entry.page);
  const forPageTypeFacets = options.context
    ? candidates.filter((page) => page.context === options.context)
    : candidates;
  const forContextFacets = options.pageType
    ? candidates.filter((page) => page.page_type === options.pageType)
    : candidates;
  const hits = candidates.filter((page) =>
    (!options.pageType || page.page_type === options.pageType) &&
    (!options.context || page.context === options.context)
  );
  return {
    hits,
    total: hits.length,
    pageTypes: facetCounts(forPageTypeFacets, "page_type"),
    contexts: facetCounts(forContextFacets, "context")
  };
}

/** Rank pages by relevance to a query. Every term must hit some field (AND).
 *  Returns most-relevant first; empty for an empty/whitespace query. */
export function rankPages(pages: PageRecord[], query: string): PageRecord[] {
  return searchPages(pages, query).hits;
}
