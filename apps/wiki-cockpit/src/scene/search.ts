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
  return foldText(query).split(/\s+/).filter(Boolean);
}

/** Rank pages by relevance to a query. Every term must hit some field (AND).
 *  Returns most-relevant first; empty for an empty/whitespace query. */
export function rankPages(pages: PageRecord[], query: string): PageRecord[] {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const scored: { page: PageRecord; score: number }[] = [];
  for (const page of pages) {
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
    if (matchedAll) scored.push({ page, score: total });
  }
  scored.sort((a, b) => b.score - a.score || a.page.title.localeCompare(b.page.title));
  return scored.map((entry) => entry.page);
}
