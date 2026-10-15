import type { PageRecord } from "../types";

export function pageTitle(ref: string, pages: PageRecord[]): string {
  return pages.find(p => p.id === ref || p.path === ref)?.title || ref;
}

// Display aliases only. The original event and the literal reply protocol stay intact.
export function readableMessage(text: string, pages: PageRecord[]): string {
  const exact = pages.find(p => p.id === text);
  if (exact) return exact.title;
  return text.replace(/`([^`\n]+)`/g, (original, ref: string) => {
    const page = pages.find(p => p.id === ref);
    return page ? page.title : original;
  });
}

export function isLocalSummaryReference(text: string): boolean {
  return /^Resumo local: [^\r\n]+\nSHA-256: [a-f0-9]{64}$/.test(text);
}
