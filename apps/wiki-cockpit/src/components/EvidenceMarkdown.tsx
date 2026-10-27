import { useMemo } from "react";
import DOMPurify from "dompurify";
import { Marked } from "marked";
import type { PageRecord, ResolvedLink } from "../types";

const markdown = new Marked({ renderer: { html: () => "" } });

export function safeEvidenceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

// Reuse verified content links. Authored Markdown never grants file access,
// starts a command or changes a task's authorization/state.
export function EvidenceMarkdown({ text, links = [], open, pages = [], language = "en", className = "boardMarkdown" }: {
  text: string; links?: ResolvedLink[]; open: (id: string) => void; pages?: PageRecord[];
  language?: string; className?: string;
}) {
  const html = useMemo(() => {
    const container = document.createElement("div");
    container.innerHTML = DOMPurify.sanitize(markdown.parse(text, { async: false }), {
      ALLOWED_TAGS: ["p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "a", "strong", "em", "del", "blockquote", "ul", "ol", "li", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "details", "summary"],
      ALLOWED_ATTR: ["href", "title", "colspan", "rowspan"]
    });
    const missing = language.startsWith("pt") ? "Link indisponível nesta revisão" : language.startsWith("es") ? "Enlace no disponible en esta revisión" : "Link unavailable in this revision";
    container.querySelectorAll("a").forEach(anchor => {
      const href = anchor.getAttribute("href") || "";
      const link = links.find(item => {
        if (item.href === href) return true;
        try { return encodeURI(item.href) === href || item.href === decodeURIComponent(href); } catch { return false; }
      });
      if (link?.kind === "page") {
        anchor.href = "#"; anchor.dataset.pageId = link.page_id;
      } else {
        const url = link?.kind === "external" ? safeEvidenceUrl(link.href)
          : link?.kind === "artifact" ? safeEvidenceUrl(link.url) : null;
        if (url) {
          anchor.href = url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
        } else {
          anchor.removeAttribute("href"); anchor.setAttribute("aria-disabled", "true"); anchor.title = missing;
        }
      }
    });
    // Display aliases affect text nodes only, never hrefs or parsed markup.
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const page = pages.find(item => item.id === node.textContent);
      if (page) node.textContent = page.title;
    }
    return container.innerHTML;
  }, [text, links, pages, language]);
  return <article className={className} dangerouslySetInnerHTML={{ __html: html }} onClick={event => {
    const anchor = (event.target as HTMLElement).closest("a");
    if (anchor?.dataset.pageId) { event.preventDefault(); open(anchor.dataset.pageId); }
  }} />;
}
