import {
  ArrowLeft,
  Blocks,
  BookOpen,
  Boxes,
  Clock3,
  Command,
  ExternalLink,
  FileText,
  Search,
  ShieldAlert
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { t } from "../data/i18n";
import {
  experiencePackLabel,
  experiencePackVersion,
  humanizePackIdentifier,
  pagesForExperiencePack,
  slotsForExperiencePack
} from "../data/experiencePacks";
import type { ExperiencePackComposition, ExperiencePackSlot, PageRecord } from "../types";
import "./pack-workbench.css";

type PackWorkbenchProps = {
  composition?: ExperiencePackComposition;
  requestedView: string;
  activeView?: ExperiencePackSlot;
  pages: PageRecord[];
  inactive?: boolean;
  onSelectView: (contribution: string) => void;
  onOpenPage: (pageId: string) => void;
  onOpenTimeline: (profile: ExperiencePackSlot) => void;
  onClose: () => void;
};

function slotLabel(composition: ExperiencePackComposition, slot: ExperiencePackSlot): string {
  return experiencePackLabel(composition, slot.contribution, slot.pack);
}

function pageTypeLabel(
  composition: ExperiencePackComposition,
  pageType: string,
  packId: string
): string {
  return experiencePackLabel(composition, pageType, packId);
}

function SlotInventory({
  title,
  rows,
  composition,
  unavailableDescriptionId
}: {
  title: string;
  rows: ExperiencePackSlot[];
  composition: ExperiencePackComposition;
  unavailableDescriptionId: string;
}) {
  return (
    <section className="packWorkbenchInventoryGroup">
      <h4>{title}</h4>
      {rows.length ? (
        <ul>
          {rows.map((row) => (
            <li key={`${row.pack}-${row.slot}-${row.contribution}`}>
              <button
                type="button"
                disabled
                aria-describedby={unavailableDescriptionId}
                title={t("packWorkbench.adapterUnavailable")}
              >
                <Command size={15} aria-hidden="true" />
                <span>
                  <strong>{slotLabel(composition, row)}</strong>
                  <small title={row.slot}>{humanizePackIdentifier(row.slot)}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : <p>{t("packWorkbench.none")}</p>}
    </section>
  );
}

export function PackWorkbench({
  composition,
  requestedView,
  activeView,
  pages,
  inactive = false,
  onSelectView,
  onOpenPage,
  onOpenTimeline,
  onClose
}: PackWorkbenchProps) {
  const surfaceRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const pageButtons = useRef(new Map<number, HTMLButtonElement>());
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const packId = activeView?.pack ?? "";
  const packVersion = activeView && composition ? experiencePackVersion(composition, packId) : undefined;
  const packSlots = activeView && composition ? slotsForExperiencePack(composition, packId) : undefined;
  const packPages = useMemo(
    () => activeView ? pagesForExperiencePack(pages, activeView.pack) : [],
    [activeView, pages]
  );
  const visiblePages = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return packPages;
    return packPages.filter((page) => [page.title, page.summary, page.page_type, page.context]
      .some((value) => value.toLocaleLowerCase().includes(normalized)));
  }, [packPages, query]);

  useEffect(() => {
    if (!surfaceRef.current) return;
    surfaceRef.current.inert = inactive;
    if (inactive) surfaceRef.current.setAttribute("aria-hidden", "true");
    else surfaceRef.current.removeAttribute("aria-hidden");
  }, [inactive]);

  useEffect(() => {
    setActiveIndex(0);
  }, [activeView?.contribution, query]);

  useEffect(() => {
    queueMicrotask(() => (headingRef.current ?? surfaceRef.current)?.focus({ preventScroll: true }));
  }, [activeView?.contribution, requestedView]);

  const onSurfaceKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };

  const focusPage = (index: number) => {
    const next = Math.min(Math.max(index, 0), visiblePages.length - 1);
    if (next < 0) return;
    setActiveIndex(next);
    pageButtons.current.get(next)?.focus();
  };

  const onPageKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const directions: Record<string, number> = {
      ArrowDown: index + 1,
      ArrowRight: index + 1,
      ArrowUp: index - 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: visiblePages.length - 1
    };
    const next = directions[event.key];
    if (next === undefined) return;
    event.preventDefault();
    focusPage(next);
  };

  if (!composition || !activeView || !packSlots) {
    return (
      <section
        ref={surfaceRef}
        className="packWorkbenchSurface packWorkbenchUnavailable"
        role="alert"
        tabIndex={-1}
        aria-labelledby="pack-workbench-unavailable-title"
        data-pack-view-requested={requestedView}
        onKeyDown={onSurfaceKeyDown}
      >
        <div>
          <ShieldAlert size={24} aria-hidden="true" />
          <span className="packWorkbenchEyebrow">{t("packWorkbench.eyebrow")}</span>
          <h2 ref={headingRef} tabIndex={-1} id="pack-workbench-unavailable-title">{t("packWorkbench.unavailable.title")}</h2>
          <p>{t("packWorkbench.unavailable.body", { view: requestedView })}</p>
          <button type="button" onClick={onClose}>
            <ArrowLeft size={16} aria-hidden="true" /> {t("packWorkbench.back")}
          </button>
        </div>
      </section>
    );
  }

  const adapterDescriptionId = `pack-adapter-unavailable-${packId.replace(/[^a-z0-9]/gi, "-")}`;
  const activeLabel = slotLabel(composition, activeView);

  return (
    <section
      ref={surfaceRef}
      className="packWorkbenchSurface"
      tabIndex={-1}
      aria-labelledby="pack-workbench-title"
      data-pack-id={packId}
      data-pack-view={activeView.contribution}
      onKeyDown={onSurfaceKeyDown}
    >
      <header className="packWorkbenchHeader">
        <div>
          <span className="packWorkbenchEyebrow"><Boxes size={14} aria-hidden="true" /> {t("packWorkbench.eyebrow")}</span>
          <h2 ref={headingRef} tabIndex={-1} id="pack-workbench-title">{activeLabel}</h2>
          <p>{t("packWorkbench.fallback", { pack: experiencePackLabel(composition, packId), version: packVersion ?? "?" })}</p>
        </div>
        <button className="packWorkbenchBack" type="button" onClick={onClose}>
          <ArrowLeft size={16} aria-hidden="true" /> {t("packWorkbench.back")}
        </button>
      </header>

      <nav className="packWorkbenchViews" aria-label={t("packWorkbench.views.aria")}>
        {packSlots.views.map((view) => (
          <button
            key={view.contribution}
            type="button"
            aria-current={view.contribution === activeView.contribution ? "page" : undefined}
            data-pack-view-option={view.contribution}
            onClick={() => onSelectView(view.contribution)}
          >
            <BookOpen size={15} aria-hidden="true" />
            <span>{slotLabel(composition, view)}</span>
          </button>
        ))}
      </nav>

      <div className="packWorkbenchBody">
        <section className="packWorkbenchPages" aria-labelledby="pack-workbench-pages-title">
          <header>
            <div>
              <h3 id="pack-workbench-pages-title">{t("packWorkbench.pages.title")}</h3>
              <p>{t("packWorkbench.pages.summary", { shown: visiblePages.length, total: packPages.length })}</p>
            </div>
            <label>
              <Search size={15} aria-hidden="true" />
              <span>{t("packWorkbench.search")}</span>
              <input
                type="search"
                value={query}
                placeholder={t("packWorkbench.searchPlaceholder")}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          </header>

          {visiblePages.length ? (
            <div className="packWorkbenchPageGrid" role="list" aria-label={t("packWorkbench.pages.aria")}>
              {visiblePages.map((page, index) => (
                <article key={page.id} role="listitem" data-pack-page-id={page.id}>
                  <button
                    ref={(target) => {
                      if (target) pageButtons.current.set(index, target);
                      else pageButtons.current.delete(index);
                    }}
                    type="button"
                    tabIndex={index === activeIndex ? 0 : -1}
                    onFocus={() => setActiveIndex(index)}
                    onKeyDown={(event) => onPageKeyDown(event, index)}
                    onClick={() => onOpenPage(page.id)}
                    aria-label={t("packWorkbench.openPageAria", { title: page.title })}
                  >
                    <span className="packWorkbenchPageTitle">
                      <FileText size={16} aria-hidden="true" />
                      <strong>{page.title}</strong>
                      <ExternalLink size={14} aria-hidden="true" />
                    </span>
                    <span className="packWorkbenchPageMeta">
                      <small>{pageTypeLabel(composition, page.page_type, packId)}</small>
                      <small data-freshness={page.freshness_state}>{t(`overlay.state.freshness.${page.freshness_state}`)}</small>
                      <small>{page.context}</small>
                    </span>
                    <span className="packWorkbenchPageSummary">{page.summary || t("packWorkbench.summaryMissing")}</span>
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <div className="packWorkbenchEmpty" role="status">
              <FileText size={22} aria-hidden="true" />
              <strong>{query ? t("packWorkbench.pages.noMatch") : t("packWorkbench.pages.empty")}</strong>
              <p>{query ? t("packWorkbench.pages.noMatchBody") : t("packWorkbench.pages.emptyBody", { pack: packId })}</p>
            </div>
          )}
        </section>

        <aside className="packWorkbenchInventory" aria-labelledby="pack-workbench-inventory-title">
          <header>
            <h3 id="pack-workbench-inventory-title">{t("packWorkbench.inventory.title")}</h3>
            <p>{t("packWorkbench.inventory.body")}</p>
          </header>

          <section className="packWorkbenchBlockPackages">
            <h4><Blocks size={15} aria-hidden="true" /> {t("packWorkbench.blocks")}</h4>
            {composition.block_packages.length ? (
              <ul>{composition.block_packages.map((blockPackage) => <li key={blockPackage}><span title={blockPackage}>{humanizePackIdentifier(blockPackage)}</span></li>)}</ul>
            ) : <p>{t("packWorkbench.none")}</p>}
          </section>

          <p id={adapterDescriptionId} className="packWorkbenchAdapterNotice">
            <ShieldAlert size={15} aria-hidden="true" />
            {t("packWorkbench.adapterUnavailable")}
          </p>

          <div className="packWorkbenchSlotInventory">
            <SlotInventory
              title={t("world.experience.packs.slot.commands")}
              rows={packSlots.commands}
              composition={composition}
              unavailableDescriptionId={adapterDescriptionId}
            />
            <SlotInventory
              title={t("world.experience.packs.slot.operations")}
              rows={packSlots.operations}
              composition={composition}
              unavailableDescriptionId={adapterDescriptionId}
            />
          </div>

          <section className="packWorkbenchTimelineProfiles">
            <h4><Clock3 size={15} aria-hidden="true" /> {t("world.experience.packs.slot.timelines")}</h4>
            <p>{t("packWorkbench.timelines.body")}</p>
            {packSlots.timelines.length ? (
              <ul>
                {packSlots.timelines.map((profile) => (
                  <li key={profile.contribution}>
                    <button type="button" onClick={() => onOpenTimeline(profile)}>
                      <Clock3 size={15} aria-hidden="true" />
                      <span><strong>{slotLabel(composition, profile)}</strong><small>{t("packWorkbench.timelines.open")}</small></span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p>{t("packWorkbench.none")}</p>}
          </section>
        </aside>
      </div>
    </section>
  );
}
