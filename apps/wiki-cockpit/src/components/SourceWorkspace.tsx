import { useMemo, useState, type ComponentProps } from "react";
import { ArrowLeft, Database, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import { t } from "../data/i18n";
import { SourceDock } from "./SourceDock";
import { SourcePlatformIcon } from "./SourcePlatformIcon";
import { sourceDisplayName, sourceKindLabel, sourcePlatformLabel } from "./sourceDockModel";

type SourceWorkspaceProps = Omit<ComponentProps<typeof SourceDock>, "embedded">;

export function SourceWorkspace(props: SourceWorkspaceProps) {
  const sources = props.bundle.sourceEntities?.sources ?? [];
  const [query, setQuery] = useState("");
  const [registryExpanded, setRegistryExpanded] = useState(false);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const ordered = [...sources].sort(
      (a, b) => b.pending_streams - a.pending_streams || a.title.localeCompare(b.title)
    );
    if (!normalized) return ordered;
    return ordered.filter((source) =>
      [source.title, source.platform, source.locator, source.source_kind]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized)
    );
  }, [query, sources]);
  const selectedId = props.sourceId || visible[0]?.source_id || sources[0]?.source_id || "";
  const overdue = sources.filter((source) => source.pending_streams > 0).length;

  return (
    <main className="sourceWorkspace" aria-label={t("source.workspace.title")}>
      <header className="sourceWorkspaceHeader">
        <div>
          <Database size={17} aria-hidden />
          <span><strong>{t("source.workspace.title")}</strong><small>{t("source.workspace.subtitle")}</small></span>
        </div>
        <button type="button" className="secondaryButton" onClick={props.onClose}>
          <ArrowLeft size={14} aria-hidden />
          {t("source.workspace.back")}
        </button>
      </header>

      <div className={`sourceWorkspaceBody${registryExpanded ? " registryExpanded" : ""}`}>
        <aside className="sourceRegistry" aria-label={t("source.list.title", { n: sources.length })}>
          <header>
            <span><strong>{t("source.registry.title")}</strong><small>{sources.length} {t("source.registry.registered")}</small></span>
            <button
              type="button"
              className="sourceRegistryExpand"
              aria-expanded={registryExpanded}
              aria-label={t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}
              title={t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}
              onClick={() => setRegistryExpanded((expanded) => !expanded)}
            >
              {registryExpanded ? <PanelLeftClose size={15} aria-hidden /> : <PanelLeftOpen size={15} aria-hidden />}
              <span>{t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}</span>
            </button>
          </header>
          <label className="sourceRegistrySearch">
            <Search size={14} aria-hidden />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("source.registry.search")} />
          </label>
          <div className="sourceRegistryFilters" aria-label={t("source.registry.filters")}>
            <span className="pill pill-muted">{t("source.registry.all")} {sources.length}</span>
            <span className="pill pill-warn">{t("source.registry.attention")} {overdue}</span>
            <span className="pill pill-good">{t("source.registry.configured")} {sources.filter((source) => source.recipe_ok).length}</span>
          </div>
          <ul className="sourceRegistryList">
            {visible.map((source) => (
              <li key={source.source_id}>
                <button
                  type="button"
                  className={source.source_id === selectedId ? "active" : ""}
                  aria-current={source.source_id === selectedId ? "true" : undefined}
                  onClick={() => props.onOpenSource?.(source.source_id)}
                >
                  <span className="sourceRegistryIcon"><SourcePlatformIcon source={source} size={16} /></span>
                  <span>
                    <strong title={source.title}>{sourceDisplayName(source.title)}</strong>
                    <small>{sourcePlatformLabel(source.platform)} · {sourceKindLabel(source.source_kind)} · {source.streams.length} {t("source.update.records")}</small>
                  </span>
                  <i className={source.pending_streams > 0 ? "attention" : "healthy"} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <SourceDock {...props} sourceId={selectedId} embedded />
      </div>
    </main>
  );
}
