// PageReader: the DEEP reading surface of the cockpit — the second level of
// the two-level read (the anchored WorldPlate summary comes first; opening the
// page docks this reader inside the 3D shell). It doubles as the 2D/static
// fallback. Markdown renders fully — marked + DOMPurify — and
// wiki-links navigate the world instead of leaving the app.

import DOMPurify from "dompurify";
import { marked } from "marked";
import type { Token } from "marked";
import {
  ArrowRight,
  CalendarClock,
  Ellipsis,
  ExternalLink,
  FileCheck2,
  Flag,
  GitBranch,
  ListChecks,
  Maximize2,
  Minimize2,
  Search,
  Sparkles,
  User,
  X
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../data/i18n";
import { contextLabel, contextStyle, isMetaPage, isRawData, landmarkGlyph, pageTypeLabel, trustColor } from "../data/presentation";
import { facetsOrder, pinnedFieldStatus, templateSpec } from "../data/templates";
import { TemplateInspector } from "./TemplateInspector";
import type { OperatorCommandCard, BriefSpec, PageContent, PageRecord, QuadrantProjection, ResolvedLink, SnapshotBundle } from "../types";
import type { OperatorPort } from "../application/ports";

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

// A rendered mermaid diagram, shrunk to fit the reader column, is unreadable for
// anything wide. Make each one open a full-screen lightbox on click, where it
// renders at natural size, pans (scroll/drag) and zooms (+/−/wheel). Pure DOM +
// CSS classes so it works inside the imperatively-built reader content.
function makeDiagramZoomable(figure: HTMLElement): void {
  figure.setAttribute("role", "button");
  figure.setAttribute("tabindex", "0");
  figure.title = t("reader.diagramExpand");
  const hint = document.createElement("span");
  hint.className = "readerDiagramHint";
  hint.textContent = t("reader.diagramExpand");
  figure.appendChild(hint);

  const open = () => {
    const overlay = document.createElement("div");
    overlay.className = "diagramLightbox";
    const stage = document.createElement("div");
    stage.className = "diagramStage";
    const svg = figure.querySelector("svg");
    if (svg) stage.appendChild(svg.cloneNode(true));
    let scale = 1;
    const applyScale = () => {
      const inner = stage.firstElementChild as HTMLElement | null;
      if (inner) inner.style.transform = `scale(${scale})`;
    };
    const bar = document.createElement("div");
    bar.className = "diagramLightboxBar";
    const mkBtn = (label: string, on: () => void) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.addEventListener("click", (e) => { e.stopPropagation(); on(); });
      return b;
    };
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey, true); };
    bar.appendChild(mkBtn("−", () => { scale = Math.max(0.4, scale - 0.25); applyScale(); }));
    bar.appendChild(mkBtn("+", () => { scale = Math.min(6, scale + 0.25); applyScale(); }));
    bar.appendChild(mkBtn("⤢", () => { scale = 1; applyScale(); })).title = t("reader.diagramReset");
    const closeBtn = mkBtn("✕", close);
    closeBtn.className = "diagramLightboxClose";
    bar.appendChild(closeBtn);
    stage.addEventListener("wheel", (e) => {
      if (!e.ctrlKey && !e.metaKey) return; // only zoom on ctrl/⌘+wheel; plain wheel pans
      e.preventDefault();
      scale = Math.min(6, Math.max(0.4, scale + (e.deltaY < 0 ? 0.15 : -0.15)));
      applyScale();
    }, { passive: false });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // The lightbox is the TOP layer: Esc closes it and only it — the
        // reader's own Esc handler (and the world ladder) must not also fire.
        e.stopImmediatePropagation();
        e.stopPropagation();
        close();
      }
      else if (e.key === "+" || e.key === "=") { scale = Math.min(6, scale + 0.25); applyScale(); }
      else if (e.key === "-") { scale = Math.max(0.4, scale - 0.25); applyScale(); }
    };
    // Capture phase: runs before the reader dock's bubbling Esc handler.
    document.addEventListener("keydown", onKey, true);
    overlay.append(bar, stage);
    document.body.appendChild(overlay);
  };
  figure.addEventListener("click", open);
  figure.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
}

// Mermaid source remains readable and safe in the core reader. Specialized
// diagram rendering is an optional v8 capability: bundling every parser made
// the default reader carry several oversized modules even when no diagram was
// opened.
async function renderMermaidBlocks(container: HTMLElement): Promise<void> {
  const blocks = [...container.querySelectorAll<HTMLElement>("pre code.language-mermaid")];
  if (blocks.length === 0) return;
  for (const code of blocks) {
    const pre = code.closest("pre");
    if (!pre) continue;
    pre.classList.add("diagramSource");
    pre.setAttribute("role", "figure");
    pre.setAttribute("aria-label", "Mermaid diagram source; optional renderer not loaded");
    const note = document.createElement("small");
    note.className = "diagramCapabilityNote";
    note.textContent = "Diagram source · optional renderer";
    pre.prepend(note);
  }
}

function decisionLabel(page: PageRecord): string {
  if (page.risk_flags.length > 0) return t("decision.risk");
  if (page.freshness_state === "stale") return t("decision.refresh");
  if (page.approved_state !== "approved") return t("decision.approval");
  return t("decision.trust");
}

function localizedRecordValue(prefix: string, value: string): string {
  const key = `${prefix}.${value}`;
  const localized = t(key);
  return localized === key ? value.replaceAll("_", " ") : localized;
}

type ActionOverview = {
  state: string;
  dueAt: string;
  overdue: boolean;
  nextAction: string;
  owner: string;
  priority: string;
  evidenceCount: number;
};

function actionOverviewForPage(bundle: SnapshotBundle, page: PageRecord): ActionOverview | null {
  const compiled = bundle.workItems?.actions.find(
    (item) => item.page_id === page.id || item.action_id === page.id
  );
  const record = { ...(page.work ?? {}), ...(compiled ?? {}) };
  if (page.page_type !== "action" && Object.keys(record).length === 0) return null;
  if (Object.keys(record).length === 0) return null;

  const ownerRecord = record.owner && typeof record.owner === "object"
    ? record.owner as Record<string, unknown>
    : null;
  const evidenceRefs = Array.isArray(record.evidence_refs) ? record.evidence_refs : page.source_refs;
  return {
    state: typeof record.state === "string" ? record.state : "open",
    dueAt: typeof record.due_at === "string" ? record.due_at : "",
    overdue: record.overdue === true,
    nextAction: typeof record.next_action === "string" ? record.next_action : "",
    owner: typeof ownerRecord?.ref === "string"
      ? ownerRecord.ref
      : typeof record.owner_ref === "string" ? record.owner_ref : "",
    priority: typeof record.priority === "string" ? record.priority : "",
    evidenceCount: evidenceRefs.length
  };
}

function pageByKey(bundle: SnapshotBundle, key: string): PageRecord | undefined {
  return bundle.pages.pages.find((page) => page.id === key || page.path === key);
}

function projectionForPage(bundle: SnapshotBundle, centerId: string | null | undefined, pageId: string): QuadrantProjection | null {
  const direct = centerId
    ? bundle.blockStacks?.anchors?.[centerId]?.derived?.quadrant_projections?.[pageId]?.[0]
    : null;
  if (direct) return direct;
  // A page can belong to a nested center even while the world is centered one
  // level above it. Preserve that honest local placement in the reader instead
  // of dropping all quadrant context when the compass is hidden behind it.
  for (const anchor of Object.values(bundle.blockStacks?.anchors ?? {})) {
    const projection = anchor.derived?.quadrant_projections?.[pageId]?.[0];
    if (projection) return projection;
  }
  return null;
}

function pageTitle(bundle: SnapshotBundle, key: string): string {
  return pageByKey(bundle, key)?.title ?? bundle.blockStacks?.anchor_tree?.nodes?.[key]?.title ?? key;
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
  bundle.graph.edges
    .filter((edge) => edge.type === "collection_member")
    .forEach((edge) => {
      if (edge.target === page.id || edge.target === page.path) {
        const member = pageByKey(bundle, edge.source);
        if (member && !hierarchy.some((item) => item.id === member.id)) {
          hierarchy.push(entry(member, t("reader.collectionMember")));
        }
      }
      if (edge.source === page.id || edge.source === page.path) {
        const collection = pageByKey(bundle, edge.target);
        if (collection && !hierarchy.some((item) => item.id === collection.id)) {
          hierarchy.push(entry(collection, t("reader.inCollection")));
        }
      }
    });

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
    .filter((backlink) => backlink.relation !== "moc_parent" && backlink.relation !== "collection_member")
    .map((backlink) => entry(
      backlink,
      backlink.relation === "source_ref"
        ? t("reader.usesAsSource")
        : t("reader.citesPage")
    ));
  (content?.backlinks ?? [])
    .filter((backlink) => backlink.relation === "moc_parent")
    .forEach((backlink) => {
      if (!hierarchy.some((item) => item.id === backlink.page_id)) hierarchy.push(entry(backlink, t("reader.below")));
    });

  return { hierarquia: hierarchy, evidencia: evidence, links, "citado-por": cited };
}

// Sectioned markdown: H2 blocks become collapsible sections so long pages
// stay navigable inside the dock.
function normalizedHeading(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/<[^>]+>/g, "")
    .replace(/[*_`~\[\]()\/]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase();
}

function markdownSections(body: string, pageTitle?: string): { title: string | null; html: string }[] {
  const tokens = marked.lexer(body);
  const firstContentIndex = tokens.findIndex((token) => token.type !== "space");
  const firstContent = firstContentIndex >= 0 ? tokens[firstContentIndex] : null;
  if (
    pageTitle &&
    firstContent?.type === "heading" &&
    firstContent.depth === 1 &&
    normalizedHeading(firstContent.text) === normalizedHeading(pageTitle)
  ) {
    // The reader header already owns the page title. Keep a different leading
    // H1 (it may be meaningful content), but remove the identical Markdown H1
    // and any whitespace before it so the first viewport starts with substance.
    tokens.splice(0, firstContentIndex + 1);
  }
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

function ActionSummaryPanel({ overview }: { overview: ActionOverview }) {
  const facts = [
    overview.dueAt
      ? { key: "due", icon: <CalendarClock size={14} aria-hidden="true" />, label: t("reader.action.due"), value: overview.dueAt }
      : null,
    overview.owner
      ? { key: "owner", icon: <User size={14} aria-hidden="true" />, label: t("reader.action.owner"), value: overview.owner }
      : null,
    overview.priority
      ? {
          key: "priority",
          icon: <Flag size={14} aria-hidden="true" />,
          label: t("reader.action.priority"),
          value: localizedRecordValue("reader.action.priority", overview.priority)
        }
      : null,
    {
      key: "evidence",
      icon: <FileCheck2 size={14} aria-hidden="true" />,
      label: t("reader.action.evidence"),
      value: String(overview.evidenceCount)
    }
  ].filter((fact): fact is NonNullable<typeof fact> => Boolean(fact));

  return (
    <section className="actionSummaryPanel" aria-label={t("reader.action.summary")}>
      <header className="actionSummaryHead">
        <div>
          <span className="actionSummaryEyebrow">{t("reader.action.summary")}</span>
          <h3>{localizedRecordValue("reader.action.state", overview.state)}</h3>
        </div>
        {overview.overdue && <span className="pill pill-warn">{t("overlay.state.actions.overdue")}</span>}
      </header>
      {overview.nextAction && (
        <div className="actionNextStep">
          <div className="actionNextStepLabel">
            <ArrowRight size={14} aria-hidden="true" />
            <span>{t("reader.action.next")}</span>
          </div>
          <p>{overview.nextAction}</p>
        </div>
      )}
      <dl className="actionFactGrid">
        {facts.map((fact) => (
          <div key={fact.key}>
            <dt>{fact.icon}{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
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
      onFocus={() => onIsolateRelation(groupKey)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onIsolateRelation(null);
      }}
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
                <span className="readerRelationTitle">{item.title}</span>
                <small>{item.context ? contextLabel(item.context) : "—"} · {item.detail}</small>
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
  loadPageContent,
  devMode,
  trail,
  packetIds,
  activeCenterId,
  onNavigatePage,
  onClose,
  onTogglePacket,
  onRunOperatorCommand,
  onComposeBrief,
  onHoverLink,
  onIsolateRelation,
  onEvidenceStep
}: {
  bundle: SnapshotBundle;
  pageId: string;
  demo: boolean;
  snapshotSource?: string;
  loadPageContent: OperatorPort["loadPageContent"];
  devMode?: boolean;
  trail: PageRecord[];
  packetIds: string[];
  activeCenterId?: string | null;
  onNavigatePage: (id: string) => void;
  onClose: () => void;
  onTogglePacket: (id: string) => void;
  onRunOperatorCommand?: (action: OperatorCommandCard) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  onHoverLink?: (id: string | null) => void;
  onIsolateRelation?: (relation: RelationGroupKey | null) => void;
  onEvidenceStep?: (ids: string[], step: number) => void;
}) {
  const page = pageByKey(bundle, pageId);
  const [content, setContent] = useState<PageContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [walkStep, setWalkStep] = useState(-1);
  const [templateOpen, setTemplateOpen] = useState(false);
  // Comfortable reading: the dock expands into a centered modal (key F).
  const [expanded, setExpanded] = useState(false);
  const dockRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const restoreFocus = () => {
        const opener = openerRef.current;
        if (opener?.isConnected && !opener.closest("[inert]")) {
          opener.focus();
          return;
        }
        document.querySelector<HTMLElement>(".commandSearch input")?.focus();
      };
      if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(restoreFocus);
      else window.setTimeout(restoreFocus, 0);
    };
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setContent(null);
    setWalkStep(-1);
    if (!page) {
      setLoading(false);
      return undefined;
    }
    loadPageContent(page.id, {
      demo,
      snapshotSource,
      snapshotId: bundle.manifest?.snapshot_id,
      integrity: bundle.manifest?.integrity,
      signal: controller.signal
    }).then((payload) => {
      if (!active) return;
      setContent(payload);
      setLoading(false);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [bundle.manifest?.integrity, bundle.manifest?.snapshot_id, demo, page, snapshotSource]);

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
      const focusables = [...dock.querySelectorAll<HTMLElement>(
        "a[href], button, details summary, input, [tabindex]:not([tabindex='-1'])"
      )].filter((element) => {
        if ((element as HTMLButtonElement).disabled || element.closest("[hidden], [aria-hidden='true'], [inert]")) return false;
        const closedDetails = element.closest<HTMLDetailsElement>("details:not([open])");
        if (closedDetails && element !== closedDetails.querySelector(":scope > summary")) return false;
        const style = element.ownerDocument.defaultView?.getComputedStyle(element);
        return style?.display !== "none" && style?.visibility !== "hidden";
      });
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
  const projection = useMemo(
    () => (page ? projectionForPage(bundle, activeCenterId, page.id) : null),
    [activeCenterId, bundle, page]
  );
  const actionOverview = useMemo(
    () => (page ? actionOverviewForPage(bundle, page) : null),
    [bundle, page]
  );
  const sections = useMemo(
    () => (content?.ok && content.body ? markdownSections(content.body, page?.title) : []),
    [content, page?.title]
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
  const graphCommand = bundle.actions.actions.find((action) => action.id === "graph-check");
  const reviewCommand = bundle.actions.actions.find((action) => action.id === "review-local-changes");
  const prCommand = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const relationOrder: RelationGroupKey[] = page.page_type === "action"
    ? ["evidencia", "hierarquia", "citado-por", "links"]
    : ["hierarquia", "evidencia", "links", "citado-por"];
  const populatedRelations = groups ? relationOrder.filter((key) => groups[key].length > 0) : [];
  const projectionFacet = projection?.facet || projection?.sub_lens;
  const projectionMarkKey = projectionFacet ? `quadrant.aqal.${projectionFacet}.mark` : "";
  const projectionMark = projectionMarkKey && t(projectionMarkKey) !== projectionMarkKey
    ? t(projectionMarkKey)
    : projection?.quadrant.toUpperCase();
  const showDecision = page.risk_flags.length > 0 || page.freshness_state !== "stale";

  return (
    <>
      {/* Comfortable-reading modal gets a scrim so the scene and the left HUD
          are dimmed and non-interactive behind the centered column. Clicking
          it collapses back to the docked reader (matching the F toggle). */}
      {expanded && <div className="readerBackdrop" onClick={() => setExpanded(false)} aria-hidden="true" />}
      <aside
        className={expanded ? "pageReader expanded" : "pageReader"}
        aria-label={t("reader.aria", { title: page.title })}
        aria-labelledby="page-reader-title"
        role="dialog"
        aria-modal="true"
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
      {/* Identity band: the page's FAMILY face — accent + (for anchors) the
          landmark glyph and horizon text; (for molds) the blueprint banner.
          The same grammar as the scene, readable in 2D. */}
      {(() => {
        const anchorIdentity = bundle.blockStacks?.anchors?.[page.id]?.identity;
        if (isMetaPage(page.page_type)) {
          return (
            <div className="readerIdentityBand meta">
              <span className="identityGlyph" aria-hidden>▤</span>
              <strong>{t("reader.mold")}</strong>
              <span>{pageTypeLabel(page.page_type)}</span>
            </div>
          );
        }
        if (anchorIdentity?.landmark) {
          return (
            <div className="readerIdentityBand anchor" style={{ borderColor: contextStyle(page.context || "system").accent }}>
              <span className="identityGlyph" aria-hidden>{landmarkGlyph(anchorIdentity.landmark)}</span>
              <strong>{anchorIdentity.horizon_text || page.title}</strong>
              <span>{anchorIdentity.landmark}</span>
            </div>
          );
        }
        return null;
      })()}
      <div className="readerHead">
        <div className="readerHeading">
          <div className="readerChips readerIdentityChips">
            <span className="pill pill-info">{contextLabel(page.context || "system")}</span>
            <button
              className={`pill pill-muted readerTypeChip${templateOpen ? " active" : ""}`}
              onClick={() => setTemplateOpen((open) => !open)}
              title={t("template.inspector.open")}
              type="button"
            >
              {pageTypeLabel(page.page_type)}
            </button>
            {projection && projectionMark && (
              <span className="pill readerPositionChip">
                {projectionMark} · {projectionFacet ? t(`facet.${projectionFacet}`) : projection.quadrant}
              </span>
            )}
          </div>
          <h2 id="page-reader-title">{page.title}</h2>
          <div className="readerStatusLine">
            <span
              className="pill"
              style={{ borderColor: trustColor(page.freshness_state === "fresh" ? "fresh" : page.freshness_state === "stale" ? "stale" : "unknown") }}
            >
              {freshnessLabel(page.freshness_state)}
            </span>
            {showDecision && <span className="pill pill-muted">{decisionLabel(page)}</span>}
            {isRawData(page.page_type) && (
              <span className="pill rawPill" title={t("world.raw")}>
                ◆ {t("world.raw")}
              </span>
            )}
            <span className="readerMetaLine">
              {[
                page.updated_at ? t("reader.updated", { when: page.updated_at.slice(0, 10) }) : "",
                t("reader.evidence", { n: page.source_refs.length })
              ].filter(Boolean).join(" · ")}
            </span>
          </div>
          {templateOpen && (
            <TemplateInspector
              spec={templateSpec(bundle, page.page_type)}
              page={page}
              status={pinnedFieldStatus(templateSpec(bundle, page.page_type), content)}
              facetsOrder={facetsOrder(bundle)}
              onComposeBrief={onComposeBrief}
              onClose={() => setTemplateOpen(false)}
            />
          )}
        </div>
        <div className="readerHeadButtons">
          <button
            className="readerClose"
            onClick={() => setExpanded((value) => !value)}
            aria-label={expanded ? t("reader.collapse") : t("reader.expand")}
            title={expanded ? t("reader.collapse") : t("reader.expand")}
            type="button"
          >
            {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          <button className="readerClose" onClick={onClose} aria-label={t("reader.close")} title={t("reader.close")} type="button">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="readerScroll">
        {actionOverview && <ActionSummaryPanel overview={actionOverview} />}
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

        {projection && (
          <details className="templatePanel projectionPanel">
            <summary>
              <span>{t("reader.projectionTitle")}</span>
              <strong>{projectionMark} · {projectionFacet ? t(`facet.${projectionFacet}`) : projection.quadrant}</strong>
            </summary>
            <div className="projectionGrid">
              <div><span>{t("reader.projectionCenter")}</span><strong>{pageTitle(bundle, projection.center)}</strong></div>
              <div><span>{t("reader.projectionHere")}</span><strong>{projection.quadrant}{projection.sub_lens ? ` · ${projection.sub_lens}` : ""}</strong></div>
              {projection.subject_center && (
                <div><span>{t("reader.projectionSubject")}</span><strong>{pageTitle(bundle, projection.subject_center)}</strong></div>
              )}
              {projection.local_quadrant_under_subject && (
                <div>
                  <span>{t("reader.projectionInside")}</span>
                  <strong>{projection.local_quadrant_under_subject}{projection.local_sub_lens_under_subject ? ` · ${projection.local_sub_lens_under_subject}` : ""}</strong>
                </div>
              )}
            </div>
            <p className="readerNotice">
              {t("reader.projectionWhy", { basis: projection.basis, reason: projection.reason || projection.through_center || projection.subject_center || "—" })}
            </p>
          </details>
        )}

        {/* Template panels: the type's declared view.panels, FINALLY rendered —
            each family reads differently (a person is a relation card, a source
            is its streams, a tool is access/cost). Data comes straight from the
            page's frontmatter; empty panels stay silent. */}
        {!loading && content?.ok && (
          <TemplatePanels
            page={page}
            spec={templateSpec(bundle, page.page_type)}
            frontmatter={(content.frontmatter ?? {}) as Record<string, unknown>}
          />
        )}

        {groups && populatedRelations.length > 0 && (
          <div className="readerRelations">
            {populatedRelations.map((key) => (
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

        <footer className="readerProvenance">
          <code>{page.path}</code>
          {devMode && (
            <a className="textButton" href={`/${page.path}`} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={13} /> {t("reader.viewSource")}
            </a>
          )}
        </footer>
      </div>
      <div className="readerActionBar" aria-label={t("reader.actions")}>
        <div className="readerActions">
          <button className={inPacket ? "secondaryButton active" : "secondaryButton"} onClick={() => onTogglePacket(page.id)} type="button">
            <ListChecks size={15} />
            <span>{inPacket ? t("reader.removePacket") : t("reader.addPacket")}</span>
          </button>
          {onComposeBrief && (
            <button
              className="secondaryButton"
              onClick={() =>
                onComposeBrief({
                  mission_kind: "refresh",
                  theme: `edit-${page.id}`,
                  grounding: { page_ids: [page.id] }
                })
              }
              type="button"
            >
              <Sparkles size={15} />
              <span>{t("reader.brief")}</span>
            </button>
          )}
          {onRunOperatorCommand && (graphCommand || reviewCommand || prCommand) && (
            <details className="readerMoreActions">
              <summary className="secondaryButton">
                <Ellipsis size={16} />
                <span>{t("reader.moreActions")}</span>
              </summary>
              <div className="readerMoreMenu">
                {graphCommand && (
                  <button className="secondaryButton" onClick={() => onRunOperatorCommand(graphCommand)} type="button">
                    <Search size={15} />
                    <span>{t("reader.connections")}</span>
                  </button>
                )}
                {reviewCommand && (
                  <button className="secondaryButton" onClick={() => onRunOperatorCommand(reviewCommand)} type="button">
                    <GitBranch size={15} />
                    <span>{t("reader.inspectChanges")}</span>
                  </button>
                )}
                {prCommand && (
                  <button className="secondaryButton" onClick={() => onRunOperatorCommand(prCommand)} type="button">
                    <ListChecks size={15} />
                    <span>{t("reader.prepareApproval")}</span>
                  </button>
                )}
              </div>
            </details>
          )}
        </div>
      </div>
      </aside>
    </>
  );
}

// --- Template panels: the type's view.panels, rendered from frontmatter -----

type PanelSpecLite = { kind: string; from?: string; label?: string; columns?: string[] };

function TemplatePanels({
  page,
  spec,
  frontmatter
}: {
  page: PageRecord;
  spec: ReturnType<typeof templateSpec>;
  frontmatter: Record<string, unknown>;
}) {
  const panels = (spec.view.panels ?? []) as PanelSpecLite[];
  const blocks: JSX.Element[] = [];

  // The person card: the relation as a fact (bond, cadence, city, dates,
  // commitments) — the Q3 rede sub-lens, readable on the page itself.
  const relationship = frontmatter.relationship as Record<string, unknown> | undefined;
  if (page.page_type === "person" && relationship && typeof relationship === "object") {
    const dates = Array.isArray(frontmatter.dates) ? (frontmatter.dates as Record<string, unknown>[]) : [];
    const commitments = Array.isArray(frontmatter.commitments) ? (frontmatter.commitments as Record<string, unknown>[]) : [];
    blocks.push(
      <div className="templatePanel personCard" key="person-card">
        <h4>{t("reader.relationCard")}</h4>
        <div className="personCardGrid">
          {relationship.kind ? <div><span>{t("reader.relation.kind")}</span><strong>{String(relationship.kind)}</strong></div> : null}
          {relationship.contact_cadence_days ? (
            <div><span>{t("reader.relation.cadence")}</span><strong>{t("reader.relation.everyNDays", { n: String(relationship.contact_cadence_days) })}</strong></div>
          ) : null}
          {relationship.city ? <div><span>{t("reader.relation.city")}</span><strong>{String(relationship.city)}</strong></div> : null}
          {relationship.since ? <div><span>{t("reader.relation.since")}</span><strong>{String(relationship.since)}</strong></div> : null}
        </div>
        {dates.length > 0 && (
          <p className="personCardRow">
            {dates.map((d, i) => (
              <span className="pill pill-muted" key={i}>{String(d.kind ?? "date")} · {String(d.date ?? "")}</span>
            ))}
          </p>
        )}
        {commitments.length > 0 && (
          <p className="personCardRow">
            {commitments.map((c, i) => (
              <span className="pill pill-warn" key={i}>{String(c.ref ?? "")} · {String(c.due ?? "")}</span>
            ))}
          </p>
        )}
      </div>
    );
  }

  for (const panel of panels) {
    const raw = panel.from ? frontmatter[panel.from] : undefined;
    if (!raw) continue;
    const label = panel.label ? t(panel.label) : panel.from ?? panel.kind;
    if (panel.kind === "list" && Array.isArray(raw) && raw.length > 0) {
      blocks.push(
        <div className="templatePanel" key={`list-${panel.from}`}>
          <h4>{label}</h4>
          <ul>
            {raw.slice(0, 12).map((item, i) => (
              <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
            ))}
          </ul>
        </div>
      );
    } else if (panel.kind === "table" && Array.isArray(raw) && raw.length > 0) {
      const columns = panel.columns ?? Object.keys((raw[0] as Record<string, unknown>) ?? {}).slice(0, 4);
      blocks.push(
        <div className="templatePanel" key={`table-${panel.from}`}>
          <h4>{label}</h4>
          <table className="templatePanelTable">
            <thead>
              <tr>{columns.map((col) => <th key={col}>{col}</th>)}</tr>
            </thead>
            <tbody>
              {raw.slice(0, 10).map((row, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col}>{String((row as Record<string, unknown>)?.[col] ?? (typeof row === "string" && col === columns[0] ? row : ""))}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  }

  // Tools read as access/cost — the ferramentas sub-lens of q4.
  if (page.page_type === "tool") {
    const rows = [
      ["platform", frontmatter.platform],
      ["access_pointer", frontmatter.access_pointer],
      ["cost", frontmatter.cost],
      ["status", frontmatter.status]
    ].filter(([, value]) => value);
    if (rows.length > 0) {
      blocks.push(
        <div className="templatePanel" key="tool-card">
          <h4>{t("reader.toolCard")}</h4>
          <div className="personCardGrid">
            {rows.map(([key, value]) => (
              <div key={String(key)}><span>{String(key)}</span><strong>{String(value)}</strong></div>
            ))}
          </div>
        </div>
      );
    }
  }

  if (blocks.length === 0) return null;
  return <div className="templatePanels">{blocks}</div>;
}
