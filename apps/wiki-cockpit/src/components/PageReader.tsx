// PageReader: the single reading surface of the cockpit. It docks inside the
// 3D shell (target-lock), doubles as the 2D/static fallback, and replaces the
// three divergent detail surfaces (SelectedCard detail, PageActionDrawer and
// the /pages detail form). Markdown renders fully — marked + DOMPurify — and
// wiki-links navigate the world instead of leaving the app.

import DOMPurify from "dompurify";
import { marked } from "marked";
import type { Token } from "marked";
import { ExternalLink, GitBranch, ListChecks, Maximize2, Minimize2, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../data/i18n";
import { contextLabel, isRawData, pageTypeLabel, trustColor } from "../data/presentation";
import { loadPageContent } from "../data/snapshot";
import type { ActionCard, PageContent, PageRecord, ResolvedLink, SnapshotBundle } from "../types";

export type RelationGroupKey = "hierarquia" | "evidencia" | "links" | "citado-por";

export function relationGroupLabel(key: RelationGroupKey): string {
  return t(`relation.${key}`);
}

type RelationEntry = {
  id: string;
  title: string;
  context: string;
  detail: string;
  freshness: string;
  missing?: boolean;
};

function freshnessLabel(state: string): string {
  if (state === "fresh") return t("trust.ok");
  if (state === "stale") return t("trust.needsRefresh");
  return t("trust.notChecked");
}

// Fenced ```mermaid blocks render as real diagrams (lazy-loaded, strict
// security level). Failures fall back to the source with an honest notice.
async function renderMermaidBlocks(container: HTMLElement): Promise<void> {
  const blocks = [...container.querySelectorAll<HTMLElement>("pre code.language-mermaid")];
  if (blocks.length === 0) return;
  try {
    const { default: mermaid } = await import("mermaid");
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark", darkMode: true });
    let index = 0;
    for (const code of blocks) {
      const pre = code.closest("pre");
      if (!pre || !pre.parentElement) continue;
      const source = code.textContent || "";
      index += 1;
      try {
        const { svg } = await mermaid.render(`readerDiagram${index}-${Date.now() % 100000}`, source);
        const wrapper = document.createElement("figure");
        wrapper.className = "readerDiagram";
        wrapper.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
        pre.replaceWith(wrapper);
      } catch {
        const note = document.createElement("p");
        note.className = "readerNotice";
        note.textContent = t("reader.diagramError");
        pre.before(note);
      }
    }
  } catch {
    /* mermaid chunk unavailable (offline static build) — code stays visible */
  }
}

function decisionLabel(page: PageRecord): string {
  if (page.risk_flags.length > 0) return t("decision.risk");
  if (page.freshness_state === "stale") return t("decision.refresh");
  if (page.approved_state !== "approved") return t("decision.approval");
  return t("decision.trust");
}

function pageByKey(bundle: SnapshotBundle, key: string): PageRecord | undefined {
  return bundle.pages.pages.find((page) => page.id === key || page.path === key);
}

function relationGroups(bundle: SnapshotBundle, page: PageRecord, content: PageContent | null): Record<RelationGroupKey, RelationEntry[]> {
  const entry = (record: { page_id?: string; id?: string; title?: string; context?: string; freshness_state?: string }, detail: string): RelationEntry => ({
    id: record.page_id || record.id || "",
    title: record.title || record.page_id || record.id || "",
    context: record.context || "",
    detail,
    freshness: record.freshness_state || "unknown"
  });

  const hierarchy: RelationEntry[] = [];
  const parent = page.moc_parent ? pageByKey(bundle, page.moc_parent) : undefined;
  if (parent) hierarchy.push(entry(parent, t("reader.above")));
  bundle.pages.pages
    .filter((candidate) => candidate.moc_parent && (candidate.moc_parent === page.path || candidate.moc_parent === page.id))
    .forEach((child) => hierarchy.push(entry(child, t("reader.below"))));

  // Without the content payload (static mode), refs still resolve against the
  // bundle — gap markers are reserved for refs that truly do not resolve.
  const localRefs = page.source_refs.map((ref) => {
    const target = bundle.pages.pages.find((item) => item.id === ref || item.path === ref || item.title === ref);
    return target
      ? ({ ref, resolved: true as const, page_id: target.id, path: target.path, title: target.title, context: target.context, page_type: target.page_type, freshness_state: target.freshness_state, approved_state: target.approved_state })
      : ({ ref, resolved: false as const });
  });
  const evidence: RelationEntry[] = (content?.source_refs ?? localRefs).map(
    (ref) =>
      ref.resolved
        ? entry(ref, t("reader.source"))
        : { id: "", title: ref.ref, context: "", detail: t("reader.noEvidence"), freshness: "unknown", missing: true }
  );

  const links: RelationEntry[] = (content?.resolved_links ?? [])
    .filter((link): link is Extract<ResolvedLink, { kind: "page" }> => link.kind === "page")
    .map((link) => entry(link, t("reader.internalLink")));

  const cited: RelationEntry[] = (content?.backlinks ?? [])
    .filter((backlink) => backlink.relation !== "moc_parent")
    .map((backlink) => entry(backlink, backlink.relation === "source_ref" ? t("reader.usesAsSource") : t("reader.citesPage")));
  (content?.backlinks ?? [])
    .filter((backlink) => backlink.relation === "moc_parent")
    .forEach((backlink) => {
      if (!hierarchy.some((item) => item.id === backlink.page_id)) hierarchy.push(entry(backlink, t("reader.below")));
    });

  return { hierarquia: hierarchy, evidencia: evidence, links, "citado-por": cited };
}

// Sectioned markdown: H2 blocks become collapsible sections so long pages
// stay navigable inside the dock.
function markdownSections(body: string): { title: string | null; html: string }[] {
  const tokens = marked.lexer(body);
  const sections: { title: string | null; tokens: Token[] }[] = [{ title: null, tokens: [] }];
  tokens.forEach((token) => {
    if (token.type === "heading" && token.depth === 2) {
      sections.push({ title: token.text, tokens: [] });
      return;
    }
    sections[sections.length - 1].tokens.push(token);
  });
  return sections
    .filter((section) => section.title !== null || section.tokens.length > 0)
    .map((section) => {
      // marked.parser expects a TokensList; carry the reference-link table over.
      const list = section.tokens as Token[] & { links: Record<string, unknown> };
      list.links = (tokens as unknown as { links: Record<string, unknown> }).links ?? {};
      return {
        title: section.title,
        html: DOMPurify.sanitize(marked.parser(list, { async: false }), { USE_PROFILES: { html: true } })
      };
    });
}

function ReaderBody({
  sections,
  resolvedLinks,
  onNavigatePage,
  onHoverLink
}: {
  sections: { title: string | null; html: string }[];
  resolvedLinks: ResolvedLink[];
  onNavigatePage: (id: string) => void;
  onHoverLink: (id: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const linkByHref = useMemo(() => {
    const map = new Map<string, ResolvedLink>();
    resolvedLinks.forEach((link) => {
      map.set(link.href, link);
      // marked percent-encodes hrefs while rendering; index both spellings.
      try {
        map.set(encodeURI(link.href), link);
      } catch {
        /* unencodable href — raw key is enough */
      }
    });
    return map;
  }, [resolvedLinks]);

  // Post-process sanitized HTML: internal links become world navigation,
  // external links open a new tab with their domain shown inline.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((anchor) => {
      const href = anchor.getAttribute("href") || "";
      if (href.startsWith("#")) return; // in-page fragment anchors stay native
      let decoded = href;
      try {
        decoded = decodeURIComponent(href);
      } catch {
        /* keep raw */
      }
      const resolved = linkByHref.get(href) ?? linkByHref.get(decoded);
      if (resolved?.kind === "page") {
        anchor.dataset.pageId = resolved.page_id;
        anchor.classList.add("readerWikiLink");
        anchor.setAttribute("href", "#");
        anchor.title = `${resolved.title} · ${contextLabel(resolved.context)}`;
      } else if (resolved?.kind === "missing") {
        anchor.classList.add("readerMissingLink");
        anchor.setAttribute("href", "#");
        anchor.title = t("reader.missingLink");
      } else if (/^[a-z][a-z0-9+.-]*:/.test(href)) {
        anchor.classList.add("readerExternalLink");
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        const domain = resolved?.kind === "external" ? resolved.domain : href.split("/")[2] || "";
        if (domain && !anchor.querySelector(".readerDomain")) {
          const badge = document.createElement("small");
          badge.className = "readerDomain";
          badge.textContent = ` (${domain})`;
          anchor.appendChild(badge);
        }
      } else {
        anchor.classList.add("readerMissingLink");
        anchor.setAttribute("href", "#");
      }
    });
    void renderMermaidBlocks(container);
  }, [linkByHref, sections]);

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const anchor = (event.target as HTMLElement).closest("a");
      if (!anchor) return;
      if (anchor.dataset.pageId) {
        event.preventDefault();
        onNavigatePage(anchor.dataset.pageId);
        return;
      }
      if (anchor.classList.contains("readerMissingLink")) event.preventDefault();
    },
    [onNavigatePage]
  );
  const handleHover = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const anchor = (event.target as HTMLElement).closest("a");
      onHoverLink(anchor?.dataset.pageId || null);
    },
    [onHoverLink]
  );

  return (
    <div className="readerBody" ref={containerRef} onClick={handleClick} onMouseOver={handleHover} onMouseOut={() => onHoverLink(null)}>
      {sections.map((section, index) =>
        section.title ? (
          <details className="readerSection" open={index < 3} key={`${section.title}-${index}`}>
            <summary>{section.title}</summary>
            <div dangerouslySetInnerHTML={{ __html: section.html }} />
          </details>
        ) : (
          <div key={`lead-${index}`} dangerouslySetInnerHTML={{ __html: section.html }} />
        )
      )}
    </div>
  );
}

function RelationSection({
  groupKey,
  entries,
  onNavigatePage,
  onIsolateRelation
}: {
  groupKey: RelationGroupKey;
  entries: RelationEntry[];
  onNavigatePage: (id: string) => void;
  onIsolateRelation: (relation: RelationGroupKey | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? entries : entries.slice(0, 5);
  return (
    <section
      className="readerRelationGroup"
      onMouseEnter={() => onIsolateRelation(groupKey)}
      onMouseLeave={() => onIsolateRelation(null)}
    >
      <header>
        <h3>{relationGroupLabel(groupKey)}</h3>
        <span className="readerCount">{entries.length}</span>
      </header>
      <ul className="plainList compactList">
        {visible.map((item, index) => (
          <li key={`${item.id || item.title}-${index}`}>
            {item.missing ? (
              <span className="readerGapMarker" title={t("reader.gapTitle")}>
                ⚠ {item.title} · {item.detail}
              </span>
            ) : (
              <button className="textButton" onClick={() => onNavigatePage(item.id)} type="button">
                {item.title}
                <small>
                  {" "}
                  · {item.context ? contextLabel(item.context) : "—"} · {item.detail}
                </small>
              </button>
            )}
          </li>
        ))}
        {entries.length === 0 && <li className="readerEmpty">{t("reader.none")}</li>}
      </ul>
      {entries.length > 5 && (
        <button className="textButton readerExpand" onClick={() => setExpanded((value) => !value)} type="button">
          {expanded ? t("reader.showLess") : t("reader.showAll", { n: entries.length })}
        </button>
      )}
    </section>
  );
}

export function PageReader({
  bundle,
  pageId,
  demo,
  snapshotSource,
  devMode,
  trail,
  packetIds,
  onNavigatePage,
  onClose,
  onTogglePacket,
  onRunAction,
  onHoverLink,
  onIsolateRelation,
  onEvidenceStep
}: {
  bundle: SnapshotBundle;
  pageId: string;
  demo: boolean;
  snapshotSource?: string;
  devMode?: boolean;
  trail: PageRecord[];
  packetIds: string[];
  onNavigatePage: (id: string) => void;
  onClose: () => void;
  onTogglePacket: (id: string) => void;
  onRunAction?: (action: ActionCard) => void;
  onHoverLink?: (id: string | null) => void;
  onIsolateRelation?: (relation: RelationGroupKey | null) => void;
  onEvidenceStep?: (ids: string[], step: number) => void;
}) {
  const page = pageByKey(bundle, pageId);
  const [content, setContent] = useState<PageContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [walkStep, setWalkStep] = useState(-1);
  // Comfortable reading: the dock expands into a centered modal (key F).
  const [expanded, setExpanded] = useState(false);
  const dockRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setContent(null);
    setWalkStep(-1);
    if (!page) {
      setLoading(false);
      return undefined;
    }
    loadPageContent(page.id, { demo, snapshotSource }).then((payload) => {
      if (!active) return;
      setContent(payload);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [demo, page, snapshotSource]);

  // Focus trap: the dock is a focused dialog; Esc returns to the scene.
  // onClose travels through a ref so parent re-renders never re-run the trap
  // (re-running stole focus from the search input on every keystroke).
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const dock = dockRef.current;
    if (!dock) return undefined;
    dock.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if ((event.key === "f" || event.key === "F") && !(event.target as HTMLElement)?.closest?.("input, textarea")) {
        setExpanded((value) => !value);
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = dock.querySelectorAll<HTMLElement>("a[href], button, details summary, input, [tabindex]:not([tabindex='-1'])");
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dock.addEventListener("keydown", onKey);
    return () => dock.removeEventListener("keydown", onKey);
  }, [pageId]);

  const groups = useMemo(() => (page ? relationGroups(bundle, page, content) : null), [bundle, content, page]);
  const sections = useMemo(
    () => (content?.ok && content.body ? markdownSections(content.body) : []),
    [content]
  );

  // Evidence walk: n/N steps the real chain page → source (→ ingestion event
  // when the linkage exists); missing hops render a gap marker, never a
  // fabricated edge.
  const walkSteps = useMemo(() => {
    if (!page || !groups) return [] as { id: string; label: string }[];
    const chain: { id: string; label: string }[] = [
      { id: page.id, label: page.title },
      ...groups.evidencia.filter((item) => !item.missing).map((item) => ({ id: item.id, label: item.title }))
    ];
    const event = bundle.timeline.events.find((item) => item.kind === "source_ingested" && item.path === page.path);
    if (event) chain.push({ id: event.id, label: t("reader.ingestionEvent", { label: event.label }) });
    return chain;
  }, [bundle.timeline.events, groups, page]);
  const walkIds = useMemo(() => walkSteps.map((step) => step.id), [walkSteps]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "n" && event.key !== "N") return;
      if ((event.target as HTMLElement)?.tagName === "INPUT" || (event.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (walkIds.length < 2) return;
      setWalkStep((current) => {
        const next = event.key === "n" ? (current + 1) % walkIds.length : (current - 1 + walkIds.length) % walkIds.length;
        onEvidenceStep?.(walkIds, next);
        return next;
      });
    };
    const dock = dockRef.current;
    dock?.addEventListener("keydown", onKey);
    return () => dock?.removeEventListener("keydown", onKey);
  }, [onEvidenceStep, walkIds]);

  if (!page) {
    return (
      <aside className="pageReader" aria-label={t("reader.notFound")} ref={dockRef} tabIndex={-1}>
        <div className="readerHead">
          <strong>{t("reader.notFound")}</strong>
          <button className="readerClose" onClick={onClose} title={t("reader.close")} type="button">
            <X size={16} />
          </button>
        </div>
        <p className="readerNotice">{t("reader.notFoundBody")}</p>
      </aside>
    );
  }

  const inPacket = packetIds.includes(page.id) || packetIds.includes(page.path);
  const graphAction = bundle.actions.actions.find((action) => action.id === "graph-check");
  const reviewAction = bundle.actions.actions.find((action) => action.id === "review-local-changes");
  const prAction = bundle.actions.actions.find((action) => action.id === "pr-summary");

  return (
    <>
      {/* Comfortable-reading modal gets a scrim so the scene and the left HUD
          are dimmed and non-interactive behind the centered column. Clicking
          it collapses back to the docked reader (matching the F toggle). */}
      {expanded && <div className="readerBackdrop" onClick={() => setExpanded(false)} aria-hidden="true" />}
      <aside
        className={expanded ? "pageReader expanded" : "pageReader"}
        aria-label={t("reader.aria", { title: page.title })}
        role="dialog"
        aria-modal={expanded}
        ref={dockRef}
        tabIndex={-1}
      >
      {trail.length > 1 && (
        <nav className="readerTrail" aria-label={t("world.trailAria")}>
          {trail.slice(-5).map((hop) => (
            <button
              className={hop.id === page.id ? "trailChip active" : "trailChip"}
              key={hop.id}
              onClick={() => onNavigatePage(hop.id)}
              type="button"
            >
              {hop.title}
            </button>
          ))}
        </nav>
      )}
      <div className="readerHead">
        <div>
          <h2>{page.title}</h2>
          <div className="readerChips">
            <span className="pill pill-info">{contextLabel(page.context || "system")}</span>
            <span className="pill pill-muted">{pageTypeLabel(page.page_type)}</span>
            <span
              className="pill"
              style={{ borderColor: trustColor(page.freshness_state === "fresh" ? "fresh" : page.freshness_state === "stale" ? "stale" : "unknown") }}
            >
              {freshnessLabel(page.freshness_state)}
            </span>
            <span className="pill pill-muted">{decisionLabel(page)}</span>
            {isRawData(page.page_type) && (
              <span className="pill rawPill" title={t("world.raw")}>
                ◆ {t("world.raw")}
              </span>
            )}
            {page.updated_at && <span className="pill pill-muted">{t("reader.updated", { when: page.updated_at.slice(0, 10) })}</span>}
            <span className="pill pill-muted">{t("reader.evidence", { n: page.source_refs.length })}</span>
          </div>
        </div>
        <div className="readerHeadButtons">
          <button
            className="readerClose"
            onClick={() => setExpanded((value) => !value)}
            title={expanded ? t("reader.collapse") : t("reader.expand")}
            type="button"
          >
            {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          <button className="readerClose" onClick={onClose} title={t("reader.close")} type="button">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="readerScroll">
        {loading && <p className="readerNotice">{t("reader.loading")}</p>}
        {!loading && content?.ok && sections.length > 0 && (
          <ReaderBody
            sections={sections}
            resolvedLinks={content.resolved_links ?? []}
            onNavigatePage={onNavigatePage}
            onHoverLink={(id) => onHoverLink?.(id)}
          />
        )}
        {!loading && !content?.ok && (
          <div className="readerFallback">
            <p>{page.summary || t("reader.noSummary")}</p>
            {page.summary_truncated && <span className="pill pill-warn">{t("reader.partial")}</span>}
            <p className="readerNotice">{t("reader.staticNotice")}</p>
          </div>
        )}

        {groups && (
          <div className="readerRelations">
            {(["hierarquia", "evidencia", "links", "citado-por"] as RelationGroupKey[]).map((key) => (
              <RelationSection
                key={key}
                groupKey={key}
                entries={groups[key]}
                onNavigatePage={onNavigatePage}
                onIsolateRelation={(relation) => onIsolateRelation?.(relation)}
              />
            ))}
          </div>
        )}

        {walkIds.length > 1 && (
          <div className="readerWalk" aria-live="polite">
            <button
              className="textButton"
              onClick={() => {
                const next = walkStep + 1 >= walkIds.length ? 0 : walkStep + 1;
                setWalkStep(next);
                onEvidenceStep?.(walkIds, next);
              }}
              type="button"
            >
              {t("reader.walk")} {walkStep >= 0 ? `${walkStep + 1}/${walkIds.length}` : t("reader.walkIdle", { n: walkIds.length })}
            </button>
            {walkStep >= 0 && walkSteps[walkStep] && <span className="readerWalkHop"> · {walkSteps[walkStep].label}</span>}
          </div>
        )}

        <div className="readerActions">
          <button className={inPacket ? "secondaryButton active" : "secondaryButton"} onClick={() => onTogglePacket(page.id)} type="button">
            <ListChecks size={15} />
            <span>{inPacket ? t("reader.removePacket") : t("reader.addPacket")}</span>
          </button>
          {onRunAction && graphAction && (
            <button className="secondaryButton" onClick={() => onRunAction(graphAction)} type="button">
              <Search size={15} />
              <span>{t("reader.connections")}</span>
            </button>
          )}
          {onRunAction && reviewAction && (
            <button className="secondaryButton" onClick={() => onRunAction(reviewAction)} type="button">
              <GitBranch size={15} />
              <span>{t("reader.inspectChanges")}</span>
            </button>
          )}
          {onRunAction && prAction && (
            <button className="secondaryButton" onClick={() => onRunAction(prAction)} type="button">
              <ListChecks size={15} />
              <span>{t("reader.prepareApproval")}</span>
            </button>
          )}
        </div>

        <footer className="readerProvenance">
          <code>{page.path}</code>
          {devMode && (
            <a className="textButton" href={`/${page.path}`} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={13} /> {t("reader.viewSource")}
            </a>
          )}
        </footer>
      </div>
      </aside>
    </>
  );
}
