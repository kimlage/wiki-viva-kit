import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent
} from "react";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronRight,
  Cloud,
  Database,
  Folder,
  FolderSync,
  GitFork,
  Globe2,
  GripVertical,
  Inbox,
  ListChecks,
  MoveDown,
  MoveUp,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Save,
  Search,
  Settings2,
  Trash2,
  X
} from "lucide-react";
import { t } from "../data/i18n";
import type { SourceGroup, SourceGroupsOperationResult } from "../types";
import { SourceDock } from "./SourceDock";
import { SourcePendingOverview } from "./SourcePendingOverview";
import { SourcePlatformIcon } from "./SourcePlatformIcon";
import { sourceDisplayName, sourceKindLabel, sourcePlatformLabel } from "./sourceDockModel";

const WIDTH_KEY = "wiki-viva.source-registry-width";
const COLLAPSED_KEY = "wiki-viva.source-registry-collapsed-groups";
const MIN_WIDTH = 280;
const DEFAULT_WIDTH = 324;

type SourceWorkspaceProps = Omit<ComponentProps<typeof SourceDock>, "embedded"> & {
  onPreviewSourceGroups?: (groups: SourceGroup[]) => Promise<SourceGroupsOperationResult>;
  onApplySourceGroups?: (groups: SourceGroup[], previewToken: string) => Promise<SourceGroupsOperationResult>;
};

function clampWidth(value: number) {
  const viewportMax = typeof window === "undefined" ? 620 : Math.min(620, Math.max(MIN_WIDTH, window.innerWidth * 0.48));
  return Math.round(Math.min(viewportMax, Math.max(MIN_WIDTH, value)));
}

function initialWidth() {
  if (typeof window === "undefined") return DEFAULT_WIDTH;
  try {
    const stored = Number(window.localStorage?.getItem(WIDTH_KEY));
    return Number.isFinite(stored) && stored > 0 ? clampWidth(stored) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

function initialCollapsed() {
  if (typeof window === "undefined") return new Set<string>();
  try {
    const value = JSON.parse(window.localStorage?.getItem(COLLAPSED_KEY) || "[]");
    return new Set<string>(Array.isArray(value) ? value.map(String) : []);
  } catch {
    return new Set<string>();
  }
}

function groupIcon(icon: SourceGroup["icon"]) {
  if (icon === "folder-remote") return <FolderSync size={15} aria-hidden />;
  if (icon === "cloud") return <Cloud size={15} aria-hidden />;
  if (icon === "web") return <Globe2 size={15} aria-hidden />;
  if (icon === "repository") return <GitFork size={15} aria-hidden />;
  if (icon === "inbox") return <Inbox size={15} aria-hidden />;
  return <Folder size={15} aria-hidden />;
}

function slugify(label: string) {
  return label
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 58) || "categoria";
}

export function SourceWorkspace(props: SourceWorkspaceProps) {
  const sources = props.bundle.sourceEntities?.sources ?? [];
  const configuredGroups = props.bundle.sourceEntities?.source_groups?.groups;
  const groupsPersisted = props.bundle.sourceEntities?.source_groups?.configured ?? true;
  const fallbackGroups: SourceGroup[] = [{
    id: "all-sources",
    label: t("source.registry.all"),
    icon: "inbox",
    source_ids: sources.map((source) => source.source_id)
  }];
  const incomingGroups = configuredGroups?.length ? configuredGroups : fallbackGroups;
  const incomingSignature = JSON.stringify(incomingGroups);
  const [query, setQuery] = useState("");
  const [registryWidth, setRegistryWidth] = useState(initialWidth);
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [groups, setGroups] = useState<SourceGroup[]>(incomingGroups);
  const [organizing, setOrganizing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [groupError, setGroupError] = useState("");
  const [newGroupLabel, setNewGroupLabel] = useState("");
  const [addingGroup, setAddingGroup] = useState(false);
  const [renamingGroup, setRenamingGroup] = useState<string | null>(null);
  const [renameLabel, setRenameLabel] = useState("");
  const [dragged, setDragged] = useState<{ type: "source" | "group"; id: string } | null>(null);
  const workspaceBody = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dirty) setGroups(JSON.parse(incomingSignature) as SourceGroup[]);
  }, [dirty, incomingSignature]);

  useEffect(() => {
    try { window.localStorage?.setItem(WIDTH_KEY, String(registryWidth)); } catch { /* unavailable in privacy mode */ }
  }, [registryWidth]);

  useEffect(() => {
    try { window.localStorage?.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])); } catch { /* unavailable in privacy mode */ }
  }, [collapsed]);

  const sourceById = useMemo(() => new Map(sources.map((source) => [source.source_id, source])), [sources]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const groupedVisible = useMemo(() => groups.map((group) => ({
    ...group,
    sources: group.source_ids
      .map((id) => sourceById.get(id))
      .filter((source): source is NonNullable<typeof source> => Boolean(source))
      .filter((source) => !normalizedQuery || [source.title, source.platform, source.locator, source.source_kind]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalizedQuery))
      .sort((a, b) => b.pending_streams - a.pending_streams || a.title.localeCompare(b.title))
  })).filter((group) => organizing || group.sources.length > 0), [groups, normalizedQuery, organizing, sourceById]);

  const selectedId = props.sourceId || "";
  const overdue = sources.filter((source) => source.pending_streams > 0).length;
  const registryExpanded = registryWidth >= 420;

  const updateGroups = (next: SourceGroup[]) => {
    setGroups(next);
    setDirty(true);
    setGroupError("");
  };

  const toggleGroup = (groupId: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const moveSource = (sourceId: string, targetGroupId: string) => {
    const next = groups.map((group) => ({
      ...group,
      source_ids: group.id === targetGroupId
        ? [...group.source_ids.filter((id) => id !== sourceId), sourceId]
        : group.source_ids.filter((id) => id !== sourceId)
    }));
    updateGroups(next);
  };

  const moveGroup = (groupId: string, targetGroupId: string) => {
    if (groupId === targetGroupId) return;
    const next = [...groups];
    const from = next.findIndex((group) => group.id === groupId);
    const to = next.findIndex((group) => group.id === targetGroupId);
    if (from < 0 || to < 0) return;
    const [group] = next.splice(from, 1);
    next.splice(to, 0, group);
    updateGroups(next);
  };

  const shiftGroup = (groupId: string, delta: number) => {
    const index = groups.findIndex((group) => group.id === groupId);
    const target = Math.max(0, Math.min(groups.length - 1, index + delta));
    if (index < 0 || index === target) return;
    const next = [...groups];
    const [group] = next.splice(index, 1);
    next.splice(target, 0, group);
    updateGroups(next);
  };

  const addGroup = () => {
    const label = newGroupLabel.trim();
    if (!label) return;
    const base = slugify(label);
    let id = base;
    let suffix = 2;
    while (groups.some((group) => group.id === id)) id = `${base}-${suffix++}`;
    updateGroups([...groups, { id, label, icon: "folder", source_ids: [] }]);
    setNewGroupLabel("");
    setAddingGroup(false);
  };

  const startRename = (group: SourceGroup) => {
    setRenamingGroup(group.id);
    setRenameLabel(group.label);
  };

  const commitRename = () => {
    const label = renameLabel.trim();
    if (renamingGroup && label) {
      updateGroups(groups.map((group) => group.id === renamingGroup ? { ...group, label } : group));
    }
    setRenamingGroup(null);
  };

  const removeEmptyGroup = (groupId: string) => {
    const target = groups.find((group) => group.id === groupId);
    if (!target || target.source_ids.length > 0 || groups.length <= 1) return;
    updateGroups(groups.filter((group) => group.id !== groupId));
  };

  const saveGroups = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setGroupError("");
    try {
      if (!props.onPreviewSourceGroups || !props.onApplySourceGroups) throw new Error(t("source.groups.unavailable"));
      const preview = await props.onPreviewSourceGroups(groups);
      if (!preview.ok || !preview.preview_token) throw new Error(preview.error || t("source.groups.failed"));
      const result = await props.onApplySourceGroups(groups, preview.preview_token);
      if (!result.ok) throw new Error(result.error || t("source.groups.failed"));
      if (result.groups) setGroups(result.groups);
      setDirty(false);
      props.onNotice(t("source.groups.saved", { id: result.operation_id || "" }));
      await props.onSourceChanged?.();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("source.groups.failed");
      if (message === "source_groups_no_changes") setDirty(false);
      else setGroupError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleDragStart = (event: DragEvent, item: { type: "source" | "group"; id: string }) => {
    setDragged(item);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", `${item.type}:${item.id}`);
  };

  const handleGroupDrop = (event: DragEvent, targetGroupId: string) => {
    event.preventDefault();
    if (dragged?.type === "source") moveSource(dragged.id, targetGroupId);
    if (dragged?.type === "group") moveGroup(dragged.id, targetGroupId);
    setDragged(null);
  };

  const resizeFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    if (!workspaceBody.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
    const left = workspaceBody.current.getBoundingClientRect().left;
    setRegistryWidth(clampWidth(event.clientX - left));
  };

  const resizeFromKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") setRegistryWidth(MIN_WIDTH);
    else if (event.key === "End") setRegistryWidth(clampWidth(620));
    else setRegistryWidth((width) => clampWidth(width + (event.key === "ArrowRight" ? 16 : -16)));
  };

  const style = { "--source-registry-width": `${registryWidth}px` } as CSSProperties;

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

      <div className={`sourceWorkspaceBody${registryExpanded ? " registryExpanded" : ""}`} style={style} ref={workspaceBody}>
        <aside className="sourceRegistry" aria-label={t("source.list.title", { n: sources.length })}>
          <header>
            <span><strong>{t("source.registry.title")}</strong><small>{sources.length} {t("source.registry.registered")}</small></span>
            <span className="sourceRegistryHeaderActions">
              <button
                type="button"
                className={`sourceRegistryOrganize${organizing ? " active" : ""}`}
                aria-pressed={organizing}
                aria-label={t("source.groups.organize")}
                title={t("source.groups.organize")}
                onClick={() => setOrganizing((value) => {
                  const next = !value;
                  if (next && !groupsPersisted) setDirty(true);
                  return next;
                })}
              >
                <Settings2 size={15} aria-hidden />
              </button>
              <button
                type="button"
                className="sourceRegistryExpand"
                aria-expanded={registryExpanded}
                aria-label={t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}
                title={t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}
                onClick={() => setRegistryWidth(registryExpanded ? DEFAULT_WIDTH : clampWidth(500))}
              >
                {registryExpanded ? <PanelLeftClose size={15} aria-hidden /> : <PanelLeftOpen size={15} aria-hidden />}
                <span>{t(registryExpanded ? "source.registry.collapse" : "source.registry.expand")}</span>
              </button>
            </span>
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

          <button
            type="button"
            className={`sourcePendingShortcut${selectedId ? "" : " active"}`}
            aria-current={selectedId ? undefined : "page"}
            onClick={() => props.onOpenSource?.("")}
          >
            <span><ListChecks size={17} aria-hidden /></span>
            <span><strong>{t("source.pending.shortcut")}</strong><small>{t("source.pending.shortcutDetail", { n: overdue })}</small></span>
            <b>{overdue}</b>
          </button>

          {organizing && (
            <div className="sourceGroupToolbar">
              {addingGroup ? (
                <form onSubmit={(event) => { event.preventDefault(); addGroup(); }}>
                  <input autoFocus value={newGroupLabel} maxLength={80} onChange={(event) => setNewGroupLabel(event.target.value)} placeholder={t("source.groups.newPlaceholder")} />
                  <button type="submit" aria-label={t("source.groups.create")}><Check size={14} aria-hidden /></button>
                  <button type="button" aria-label={t("source.groups.cancel")} onClick={() => setAddingGroup(false)}><X size={14} aria-hidden /></button>
                </form>
              ) : (
                <button type="button" onClick={() => setAddingGroup(true)}><Plus size={14} aria-hidden /> {t("source.groups.create")}</button>
              )}
              <button type="button" className="sourceGroupSave" disabled={!dirty || saving} onClick={saveGroups}>
                <Save size={14} aria-hidden /> {saving ? t("source.groups.saving") : t("source.groups.save")}
              </button>
            </div>
          )}
          {groupError && <p className="sourceGroupError">{groupError}</p>}

          <div className="sourceRegistryGroups" aria-label={t("source.groups.title")}>
            {groupedVisible.map((group, groupIndex) => {
              const isCollapsed = collapsed.has(group.id) && !normalizedQuery;
              return (
                <section
                  className={`sourceRegistryGroup${dragged?.type === "source" ? " acceptsSource" : ""}`}
                  key={group.id}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => handleGroupDrop(event, group.id)}
                >
                  <div
                    className="sourceGroupHeader"
                    draggable={organizing}
                    onDragStart={(event) => handleDragStart(event, { type: "group", id: group.id })}
                    onDragEnd={() => setDragged(null)}
                  >
                    {organizing && <GripVertical className="sourceGroupDrag" size={14} aria-hidden />}
                    {renamingGroup === group.id ? (
                      <div className="sourceGroupToggle sourceGroupRenameRow">
                        {isCollapsed ? <ChevronRight size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
                        <span className="sourceGroupIcon">{groupIcon(group.icon)}</span>
                        <input
                          autoFocus
                          value={renameLabel}
                          maxLength={80}
                          aria-label={t("source.groups.rename")}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => setRenameLabel(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") { event.preventDefault(); commitRename(); }
                            if (event.key === "Escape") setRenamingGroup(null);
                          }}
                        />
                        <small>{group.source_ids.length}</small>
                      </div>
                    ) : (
                      <button type="button" className="sourceGroupToggle" aria-expanded={!isCollapsed} onClick={() => toggleGroup(group.id)}>
                        {isCollapsed ? <ChevronRight size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
                        <span className="sourceGroupIcon">{groupIcon(group.icon)}</span>
                        <strong>{group.label}</strong>
                        <small>{group.source_ids.length}</small>
                      </button>
                    )}
                    {organizing && (
                      <span className="sourceGroupActions">
                        {renamingGroup === group.id ? (
                          <button type="button" aria-label={t("source.groups.confirmRename")} onClick={commitRename}><Check size={13} aria-hidden /></button>
                        ) : (
                          <button type="button" aria-label={t("source.groups.rename")} onClick={() => startRename(group)}><Pencil size={13} aria-hidden /></button>
                        )}
                        <button type="button" disabled={groupIndex === 0} aria-label={t("source.groups.moveUp")} onClick={() => shiftGroup(group.id, -1)}><MoveUp size={13} aria-hidden /></button>
                        <button type="button" disabled={groupIndex === groups.length - 1} aria-label={t("source.groups.moveDown")} onClick={() => shiftGroup(group.id, 1)}><MoveDown size={13} aria-hidden /></button>
                        <button type="button" disabled={group.source_ids.length > 0 || groups.length <= 1} aria-label={t("source.groups.remove")} onClick={() => removeEmptyGroup(group.id)}><Trash2 size={13} aria-hidden /></button>
                      </span>
                    )}
                  </div>
                  {!isCollapsed && (
                    <ul className="sourceRegistryList">
                      {group.sources.map((source) => (
                        <li
                          key={source.source_id}
                          draggable={organizing}
                          onDragStart={(event) => handleDragStart(event, { type: "source", id: source.source_id })}
                          onDragEnd={() => setDragged(null)}
                        >
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
                          {organizing && (
                            <label className="sourceMoveSelect">
                              <span>{t("source.groups.moveSource")}</span>
                              <select value={group.id} onChange={(event) => moveSource(source.source_id, event.target.value)}>
                                {groups.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                              </select>
                            </label>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        </aside>

        <div
          className="sourceRegistryResize"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("source.registry.resize")}
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={clampWidth(620)}
          aria-valuenow={registryWidth}
          tabIndex={0}
          onDoubleClick={() => setRegistryWidth(DEFAULT_WIDTH)}
          onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
          onPointerMove={resizeFromPointer}
          onKeyDown={resizeFromKeyboard}
        ><span /></div>

        {selectedId ? (
          <SourceDock {...props} sourceId={selectedId} embedded />
        ) : (
          <SourcePendingOverview
            sources={sources}
            groups={groups}
            demo={props.demo}
            onOpenSource={props.onOpenSource}
            onPreviewRefresh={props.onPreviewRefresh}
            onRunRefresh={props.onRunRefresh}
            onSourceChanged={props.onSourceChanged}
            onNotice={props.onNotice}
          />
        )}
      </div>
    </main>
  );
}
