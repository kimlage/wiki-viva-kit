import { useMemo, useState, type ComponentProps } from "react";
import { ArrowLeft, Database, Search } from "lucide-react";
import { t } from "../data/i18n";
import { SourceDock } from "./SourceDock";
import { sourceKindLabel } from "./sourceDockModel";

type SourceWorkspaceProps = Omit<ComponentProps<typeof SourceDock>, "embedded">;

export function SourceWorkspace(props: SourceWorkspaceProps) {
  const sources = props.bundle.sourceEntities?.sources ?? [];
  const [query, setQuery] = useState("");
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

      <div className="sourceWorkspaceBody">
        <aside className="sourceRegistry" aria-label={t("source.list.title", { n: sources.length })}>
          <header>
            <span><strong>{t("source.registry.title")}</strong><small>{sources.length} {t("source.registry.registered")}</small></span>
            {overdue > 0 && <span className="pill pill-warn">{overdue} {t("source.registry.attention")}</span>}
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
                  <span className="sourceRegistryIcon"><Database size={15} aria-hidden /></span>
                  <span><strong>{source.title}</strong><small>{sourceKindLabel(source.source_kind)} · {source.streams.length} {t("source.update.records")}</small></span>
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
