import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Database, Focus, GitBranch, Globe2, Layers, List, ListChecks, Network, Search, X } from "lucide-react";
import type { NavigationPort, OperatorPort } from "../application/ports";
import type { RuntimeConfig } from "../data/runtimeConfig";
import { contextLabel, pageTypeLabel } from "../data/presentation";
import { MAP_RELATION_TYPES, mapRelationStyle } from "../data/mapRelations";
import { t } from "../data/i18n";
import { localizedEncodingText, visualEncodingResolver } from "../data/visualEncoding";
import type { WorldPatch, WorldRoute } from "../router";
import { focusColorToken } from "../scene/focusMap";
import { buildIntegratedMap, indexIntegratedGraph, MAP_EDGE_BUDGET, MAP_NODE_BUDGET } from "../scene/integratedMap";
import type { MapPerspective } from "../scene/integratedMap";
import { searchPages } from "../scene/search";
import type { GraphNode, PageRecord, SnapshotBundle } from "../types";
import type { OverlayId } from "../world/contracts";
import { AppearanceControl } from "./AppearanceControl";
import { ConnectedMapCanvas } from "./ConnectedMapCanvas";
import "./focus-map.css";

const PageReader = lazy(() => import("./PageReader").then(module => ({ default: module.PageReader })));
const OVERLAYS: OverlayId[] = ["attention", "freshness", "actions", "ownership", "evidence", "quality"];
const PERSPECTIVES = [{id:"network",Icon:Network},{id:"areas",Icon:Layers},{id:"evidence",Icon:Database},{id:"work",Icon:ListChecks}] as const;
const RESULT_LIMIT = 100;
const relationLabel = (type: string) => t(`map.rel.${MAP_RELATION_TYPES.has(type) ? type : "unknown"}`);

type Props = {
  bundle: SnapshotBundle; runtime: RuntimeConfig; route: WorldRoute;
  navigation: NavigationPort; loadPageContent: OperatorPort["loadPageContent"];
  onSnapshotMismatch?: () => void;
};

/** Connected, read-only navigation over one integrity-checked revision. */
export function FocusMapView({bundle,runtime,route,navigation,loadPageContent,onSnapshotMismatch}: Props) {
  const pages = bundle.pages.pages;
  const pageIndex = useMemo(() => new Map(pages.flatMap(page => [[page.id,page],[page.path,page]])), [pages]);
  const graph = useMemo(() => indexIntegratedGraph(bundle.graph), [bundle.graph]);
  const selectedPage = pageIndex.get(route.query.page || route.pageId || "");
  const requestedFocus = route.query.mapFocus || route.query.center || bundle.manifest.root_page_id || "";
  const focusId = graph.nodes.has(requestedFocus) ? requestedFocus : bundle.graph.nodes[0]?.id || null;
  // Explicit-focus bookmarks retain their neighborhood. A fresh entry starts
  // with the complete bounded overview and writes that choice once.
  const scope = route.query.mapScope || (route.query.mapFocus ? "focus" : "all");
  const perspective: MapPerspective = route.query.mapPerspective || "network";
  const expansionKey = JSON.stringify(route.query.mapExpanded);
  const pinnedPage = graph.nodes.size > MAP_NODE_BUDGET ? selectedPage?.id : null;
  const pinnedEdge = graph.nodes.size > MAP_NODE_BUDGET || graph.edges.length > MAP_EDGE_BUDGET ? route.query.mapEdge : "";
  const model = useMemo(() => buildIntegratedMap(graph, {
    focusId, selectedId:pinnedPage, selectedEdge:pinnedEdge, scope, perspective,
    expandedIds:JSON.parse(expansionKey) as string[]
  }), [graph,focusId,pinnedPage,pinnedEdge,scope,perspective,expansionKey]);
  const selectedEdge = graph.edgeByKey.get(route.query.mapEdge);
  const mode = route.query.mapMode || "graph";
  const colorMode = route.query.mapColor || "topic";
  const overlay: OverlayId = OVERLAYS.includes(route.query.overlay as OverlayId) ? route.query.overlay as OverlayId : "freshness";
  const search = useMemo(() => route.query.q.trim() ? searchPages(pages,route.query.q).hits :
    [...pages].sort((a,b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id)), [pages,route.query.q]);
  const [searchOpen,setSearchOpen] = useState(Boolean(route.query.q));
  const [panelTab,setPanelTab] = useState<"summary"|"sources">("summary");
  const [motion,setMotion] = useState(true);
  const [notice,setNotice] = useState("");
  const [relationshipWindow,setRelationshipWindow] = useState({id:"",count:100});
  const searchRef = useRef<HTMLInputElement>(null), searchArea = useRef<HTMLDivElement>(null), surfaceRef = useRef<HTMLElement>(null);
  const panelRef = useRef<HTMLElement>(null), readerOpener = useRef<HTMLElement|SVGElement|null>(null), edgeOpener = useRef<HTMLElement|SVGElement|null>(null);
  const patch = (value: WorldPatch, replace=false) => navigation.dispatch({type:"patch-world",route,patch:value,replace});
  const activeElement = () => document.activeElement instanceof HTMLElement || document.activeElement instanceof SVGElement ? document.activeElement : null;
  const restoreFocus = (opener: HTMLElement|SVGElement|null) => window.requestAnimationFrame(() => {
    if (opener?.isConnected && opener.getBoundingClientRect().width>0 && !opener.closest("[inert]")) opener.focus();
    else searchRef.current?.focus();
  });
  const openPage = (key: string, read=route.query.reader) => {
    const page = pageIndex.get(key);
    if (!page) {setNotice(t("map.unavailable",{id:key}));return;}
    const opener = activeElement();
    if (opener && !opener.closest(".focusMapInspector")) readerOpener.current=opener;
    setNotice("");setSearchOpen(false);setPanelTab("summary");
    patch({context:page.context||null,pageId:page.id,page:page.id,reader:read,mapEdge:null,dock:null,tray:null,packView:null});
    if (window.matchMedia("(max-width: 760px)").matches) window.requestAnimationFrame(() => {
      // Do not steal focus if the user has already reached a reader control
      // during the navigation frame (including a reused canonical reader).
      const panel=panelRef.current;
      if(panel&&!panel.contains(document.activeElement))panel.focus({preventScroll:true});
    });
  };
  const closeReader = () => {patch({reader:false});restoreFocus(readerOpener.current);};
  const openEdge = (key: string) => {
    const opener=activeElement();if(opener&&!opener.closest(".focusMapInspector"))edgeOpener.current=opener;
    patch({mapEdge:key});
  };
  const closeEdge = () => {patch({mapEdge:null});restoreFocus(edgeOpener.current);};
  const clearHighlight = () => patch({mapEdge:null,page:null,pageId:null,reader:false});
  const focusCurrent = () => {if(selectedPage)patch({mapFocus:selectedPage.id,mapScope:"focus",mapExpanded:[],mapEdge:null});};
  const overview = () => patch({mapScope:"all",mapExpanded:[]});
  useEffect(() => {
    if (route.query.dock || route.query.tray || route.query.packView || !route.query.mapScope || (!route.query.mapFocus&&focusId)) {
      navigation.dispatch({type:"patch-world",route,patch:{dock:null,tray:null,packView:null,mapScope:scope,
        ...(!route.query.mapFocus&&focusId ? {mapFocus:focusId} : {})},replace:true});
    }
  }, [focusId,navigation,route,scope]);
  useEffect(() => {
    const outside=(event:PointerEvent)=>{if(!searchArea.current?.contains(event.target as Node))setSearchOpen(false);};
    document.addEventListener("pointerdown",outside);return()=>document.removeEventListener("pointerdown",outside);
  }, []);
  useEffect(() => {
    const onKey=(event:KeyboardEvent)=>{
      if(event.altKey||event.ctrlKey||event.metaKey||event.defaultPrevented||surfaceRef.current?.querySelector(".pageReader.expanded"))return;
      const editing=(event.target as HTMLElement)?.closest?.("input,textarea,select,[contenteditable='true']");
      if(event.key==="/"&&!editing){event.preventDefault();setSearchOpen(true);searchRef.current?.focus();}
      else if(event.key==="Escape"&&!editing&&surfaceRef.current?.contains(event.target as Node)) {
        if(searchOpen){event.preventDefault();setSearchOpen(false);searchRef.current?.focus();}
        else if(route.query.mapEdge){event.preventDefault();clearHighlight();surfaceRef.current?.querySelector<HTMLElement>(".focusMapCanvas")?.focus({preventScroll:true});}
        else if(route.query.reader){event.preventDefault();closeReader();}
        else if(selectedPage){event.preventDefault();clearHighlight();surfaceRef.current?.querySelector<HTMLElement>(".focusMapCanvas")?.focus({preventScroll:true});}
      }
    };
    document.addEventListener("keydown",onKey);return()=>document.removeEventListener("keydown",onKey);
  });
  const encodingFor=(node:GraphNode)=>{
    if(colorMode==="state") {
      const encoding=visualEncodingResolver.resolve(node,overlay);
      return {color:encoding.color,label:localizedEncodingText(encoding),symbol:encoding.symbol,ring:encoding.ring};
    }
    return {...focusColorToken(node,colorMode),symbol:"",ring:"solid"};
  };
  const legend=colorMode==="state" ? visualEncodingResolver.legend(overlay,model.nodes.map(item=>item.node)).filter(entry=>entry.visibleCount>0)
    .map(entry=>({key:entry.state,color:entry.color,label:`${entry.symbol} ${localizedEncodingText(entry)}`,count:entry.visibleCount})) :
    [...model.nodes.reduce((entries,item)=>{const token=focusColorToken(item.node,colorMode);entries.set(token.key,{...token,count:(entries.get(token.key)?.count||0)+1});return entries;},new Map<string,{key:string;color:string;label:string;count:number}>()).values()];
  const edgeTypes=[...model.edges.reduce((types,{edge})=>types.set(edge.type,(types.get(edge.type)||0)+1),new Map<string,number>())].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  const related=selectedPage ? graph.incident.get(selectedPage.id)||[] : model.edges;
  const windowSize=relationshipWindow.id===selectedPage?.id ? relationshipWindow.count : 100;
  const sources=selectedPage?.source_refs||[];
  const citations=selectedPage ? graph.edges.filter(({edge})=>edge.type==="source_ref"&&(edge.target===selectedPage.id||edge.target===selectedPage.path)) : [];
  const selectedVisible=model.nodes.some(node=>node.id===selectedPage?.id);
  const expandable=model.nodes.find(node=>node.id===selectedPage?.id);
  const titleFor=(key:string)=>pageIndex.get(key)?.title||graph.nodes.get(key)?.title||key;
  const canonicalHref=(page:PageRecord)=>navigation.hrefForPatch(route,{pageId:page.id,page:page.id,reader:true,mapEdge:null,dock:null,tray:null,packView:null});
  const renderReference=(key:string)=>{
    const page=pageIndex.get(key);
    return page ? <button type="button" onClick={()=>openPage(page.id,true)}><Database size={15}/><span><strong>{page.title}</strong><small>{contextLabel(page.context)} · {pageTypeLabel(page.page_type)}</small></span><ArrowRight size={15}/></button> :
      <div className="focusMapUnavailable"><code>{key}</code><span>{t("map.sourceUnavailable")}</span></div>;
  };
  const relations=<details className="focusMapRelations" open><summary>{t(selectedPage?"map.relationships":"map.visibleRelationships")} ({related.length})</summary>
    <ul aria-label={t("map.connections")}>{related.slice(0,windowSize).map(item=><li key={item.key}><button type="button" data-edge-id={item.edge.id||""} aria-pressed={route.query.mapEdge===item.key} onClick={()=>openEdge(item.key)}>
      <GitBranch size={15}/><span><strong>{relationLabel(item.edge.type)}</strong><small>{titleFor(item.edge.source)} {item.edge.direction==="directed"?"→":"—"} {titleFor(item.edge.target)}</small></span></button></li>)}</ul>
    {!related.length&&<p>{t("map.relationshipsEmpty")}</p>}
    {related.length>windowSize&&<button type="button" onClick={()=>setRelationshipWindow({id:selectedPage?.id||"",count:windowSize+100})}>{t("map.connections")} · {windowSize} / {related.length} · +100</button>}
  </details>;

  return <main className="focusMap" data-testid="focus-map" data-inspector={selectedPage||route.query.mapEdge?"open":"closed"} data-reader={route.query.reader?"on":"off"} ref={surfaceRef}>
    <header className="focusMapHeader">
      <div className="focusMapBrand"><Network size={26} aria-hidden="true"/><div><span className="focusMapEyebrow">Wiki Viva</span><h1>{t("map.title")}</h1></div></div>
      <div className="focusMapSearch" ref={searchArea}>
        <Search size={17} aria-hidden="true"/><input id="focus-map-search" data-testid="focus-search" ref={searchRef} type="search" aria-label={t("map.search")} aria-expanded={searchOpen} aria-controls="map-search-results"
          value={route.query.q} placeholder={t("map.searchPlaceholder")} onFocus={()=>setSearchOpen(true)} onChange={event=>{setSearchOpen(true);patch({q:event.target.value||null},true);}}
          onKeyDown={event=>{
            if(event.key==="Enter"&&search[0]){event.preventDefault();openPage(search[0].id);}
            if(event.key==="ArrowDown"){event.preventDefault();surfaceRef.current?.querySelector<HTMLElement>(".focusMapSearchResults button")?.focus();}
            if(event.key==="Escape"){event.preventDefault();setSearchOpen(false);}
          }}/><kbd>/</kbd>
        {searchOpen&&<div className="focusMapSearchPopover" id="map-search-results">
          <div className="focusMapSectionHeading"><span>{t("map.searchScope",{n:search.length})}</span><button type="button" aria-label={t("map.close")} onClick={()=>setSearchOpen(false)}><X size={16}/></button></div>
          <ul className="focusMapSearchResults">{search.slice(0,RESULT_LIMIT).map(page=><li key={page.id}><button type="button" aria-current={selectedPage?.id===page.id?"page":undefined} onClick={()=>openPage(page.id)} data-page-id={page.id}><strong>{page.title}</strong><span>{contextLabel(page.context)} · {pageTypeLabel(page.page_type)}</span></button></li>)}</ul>
          {!search.length&&<p>{t("map.emptySearch")}</p>}{search.length>RESULT_LIMIT&&<p>{t("map.moreSearch",{n:RESULT_LIMIT})}</p>}
        </div>}
      </div>
      <div className="focusMapHeaderActions"><span className="focusMapReadOnly">{t(route.demo?"map.synthetic":"map.readOnly")}</span><AppearanceControl/>
        <button type="button" onClick={()=>patch({projection:null,mapMode:null,mapFocus:null,mapExpanded:[],mapColor:null,mapEdge:null,mapPerspective:null,mapScope:null,mapRelation:null})}><Globe2 size={15}/>{t("map.original")}</button>
      </div>
    </header>
    <div className="focusMapBody">
      <section className="focusMapExplorer" aria-label={t("map.title")}>
        <div className="focusMapToolbar"><div className="focusMapPerspectives" role="group" aria-label={t("map.subtitle")}>{PERSPECTIVES.map(({id,Icon})=><button type="button" key={id} data-testid={`map-perspective-${id}`} aria-pressed={perspective===id} onClick={()=>patch({mapPerspective:id})}><Icon size={17}/>{t(`map.${id}`)}</button>)}</div>
          <div className="focusMapViewSwitch" role="group" aria-label={t("map.graph")}><button type="button" data-testid="map-graph-mode" aria-pressed={mode==="graph"} onClick={()=>patch({mapMode:"graph"})}><Network size={16}/>{t("map.graph")}</button><button type="button" data-testid="map-list-mode" aria-pressed={mode==="list"} onClick={()=>patch({mapMode:"list"})}><List size={16}/>{t("map.list")}</button></div>
        </div>
        <div className="focusMapContextBar"><div><p className="focusMapPerspectiveHint">{t(`map.${perspective}Hint`)}</p><p className="focusMapCounts" data-testid="focus-counts">{t("map.counts",{shown:model.counts.shownNodes,total:model.counts.totalNodes,edges:model.counts.shownEdges,totalEdges:model.counts.totalEdges})}</p></div>
          <button type="button" aria-pressed={scope==="all"} data-testid="map-overview" onClick={overview}><ArrowLeft size={14}/>{t("map.all")}</button>
        </div>
        <div className="focusMapEncoding"><label>{t("map.color")}<select aria-label={t("map.color")} value={colorMode} onChange={event=>patch({mapColor:event.target.value as "topic"|"category"|"state"})}><option value="topic">{t("map.topic")}</option><option value="category">{t("map.category")}</option><option value="state">{t("map.state")}</option></select></label>
          {colorMode==="state"&&<label>{t("map.metric")}<select aria-label={t("map.metric")} value={overlay} onChange={event=>patch({overlay:event.target.value})}>{OVERLAYS.map(id=><option key={id} value={id}>{t(`world.overlay.${id}`)}</option>)}</select></label>}
          <div className="focusMapLegend" aria-label={t("map.legend")}>{legend.map(item=><span key={item.key}><i style={{backgroundColor:item.color}} aria-hidden="true"/>{item.label}<small>{item.count}</small></span>)}</div>
        </div>
        {mode==="graph" ? <ConnectedMapCanvas model={model} perspective={perspective} focusId={focusId} selectedId={selectedPage?.id||null} selectedEdge={route.query.mapEdge} relation={route.query.mapRelation} motion={motion} encodingFor={encodingFor} relationLabel={relationLabel} onSelect={id=>openPage(id)} onEdge={openEdge} onClear={clearHighlight}/> :
          <ul className="focusMapItemList" aria-label={t("map.searchIndex")}>{model.nodes.map(item=>{const encoding=encodingFor(item.node);return <li key={item.id}><button type="button" onClick={()=>openPage(item.id)} aria-current={selectedPage?.id===item.id?"page":undefined}><i style={{backgroundColor:encoding.color}} aria-hidden="true"/><span><strong>{item.node.title}</strong><small>{pageTypeLabel(item.node.page_type)} · {contextLabel(item.node.context)} · {encoding.symbol} {encoding.label}</small></span><ArrowRight size={16}/></button></li>;})}</ul>}
        <div className="focusMapRelationLegend" role="group" aria-label={t("map.relationsLegend")}><button type="button" aria-pressed={!route.query.mapRelation} onClick={()=>patch({mapRelation:null})}>{t("map.allRelations")}</button>{edgeTypes.map(([type,count])=>{const style=mapRelationStyle(type);return <button type="button" key={type} data-relation-type={type} aria-pressed={route.query.mapRelation===type} onClick={()=>patch({mapRelation:route.query.mapRelation===type?null:type})}><svg className="focusMapRelationSwatch" width="34" height="12" aria-hidden="true"><path d="M 1 6 H 33" stroke={style.color} strokeDasharray={style.dash}/></svg>{relationLabel(type)}<small>{count}</small></button>;})}</div>
        <div className="focusMapStatusBar"><span>{t("map.legendHint")}</span><label><input type="checkbox" checked={motion} onChange={event=>setMotion(event.target.checked)}/>{t("map.motion")}</label></div>
        {(model.counts.hiddenCandidateNodes>0||model.counts.outsideFocusNodes>0||model.counts.unresolvedEdges>0||model.counts.omittedEdges>0)&&<p className="focusMapLimits">
          {model.counts.outsideFocusNodes>0&&<span>{t("map.outside",{n:model.counts.outsideFocusNodes})}.</span>} {model.counts.hiddenCandidateNodes>0&&<span>{t("map.budget",{n:model.counts.hiddenCandidateNodes})}.</span>} {model.counts.unresolvedEdges>0&&<span>{t("map.unresolved",{n:model.counts.unresolvedEdges})}.</span>} {model.counts.omittedEdges>0&&<span>{t("map.omittedEdges",{n:model.counts.omittedEdges})}.</span>}
        </p>}
        {!model.nodes.length&&<p role="status">{t("map.noPages")}</p>}{requestedFocus!==focusId&&<p role="status">{t("map.missingFocus")}</p>}{model.ignoredExpansionIds.length>0&&<p>{t("map.ignoredExpansion",{n:model.ignoredExpansionIds.length})}</p>}
      </section>
      <aside className="focusMapInspector" aria-label={t("map.context")} ref={panelRef} tabIndex={-1}>
        {route.query.mapEdge ? <section className="focusMapEdgeDetails" data-testid="focus-edge-details">
          <div className="focusMapSectionHeading"><span className="focusMapEyebrow">{t("map.relation")}</span><button type="button" aria-label={t("map.close")} onClick={closeEdge}><X size={17}/></button></div>
          <h2>{selectedEdge?relationLabel(selectedEdge.edge.type):t("map.relationUnavailable")}</h2>
          {selectedEdge&&<>
            <div className="focusMapEdgeEndpoints"><button type="button" disabled={!pageIndex.has(selectedEdge.edge.source)} onClick={()=>openPage(selectedEdge.edge.source)}>{titleFor(selectedEdge.edge.source)}</button><span>{selectedEdge.edge.direction==="directed"?"→":"—"}</span><button type="button" disabled={!pageIndex.has(selectedEdge.edge.target)} onClick={()=>openPage(selectedEdge.edge.target)}>{titleFor(selectedEdge.edge.target)}</button></div>
            <dl className="focusMapFacts"><dt>{t("map.direction")}</dt><dd>{t(selectedEdge.edge.direction==="directed"?"map.directed":selectedEdge.edge.direction==="undirected"?"map.undirected":"map.noDirection")}</dd><dt>{t("map.observed")}</dt><dd>{selectedEdge.edge.observed_at||t("map.notRecorded")}</dd></dl>
            <h3>{t("map.provenance")}</h3>
            {selectedEdge.edge.provenance&&Object.keys(selectedEdge.edge.provenance).length ? <>
              <code className="focusMapOriginPath">{selectedEdge.edge.provenance.path||selectedEdge.edge.provenance.page_id||t("map.notRecorded")}</code>
              {(()=>{const origin=pageIndex.get(selectedEdge.edge.provenance.page_id||selectedEdge.edge.provenance.path||"");return origin ? <a href={canonicalHref(origin)} onClick={event=>{event.preventDefault();openPage(origin.id,true);}}>{t("map.openOrigin")}<ArrowRight size={16}/></a> : null;})()}
            </> : <p>{t("map.notRecorded")}</p>}
            <details className="focusMapOriginalRecord"><summary>{t("map.technical")}</summary><pre data-testid="map-original-record"><code>{JSON.stringify(selectedEdge.edge,null,2)}</code></pre></details>
            {(()=>{const n=graph.edges.filter(({edge})=>(edge.source===selectedEdge.edge.source&&edge.target===selectedEdge.edge.target)||(edge.source===selectedEdge.edge.target&&edge.target===selectedEdge.edge.source)).length;return n>1 ? <p className="focusMapSmall">{t("map.parallel",{n})}</p> : null;})()}
          </>}
        </section> : selectedPage ? <>
          <div className="focusMapInspectorHeader"><div className="focusMapSectionHeading"><span className="focusMapEyebrow">{t("map.selected")}</span><button type="button" data-testid="map-clear-selection" aria-label={t("map.close")} onClick={()=>{patch({page:null,pageId:null,reader:false,mapEdge:null});restoreFocus(readerOpener.current);}}><X size={17}/></button></div><h2>{selectedPage.title}</h2><div className="focusMapPageMeta"><span>{contextLabel(selectedPage.context)}</span><span>{pageTypeLabel(selectedPage.page_type)}</span></div></div>
          <div className="focusMapPanelTabs" role="group" aria-label={selectedPage.title}>
            <button type="button" aria-pressed={!route.query.reader&&panelTab==="summary"} onClick={()=>{setPanelTab("summary");patch({reader:false});}}>{t("map.summary")}</button>
            <button type="button" aria-pressed={!route.query.reader&&panelTab==="sources"} onClick={()=>{setPanelTab("sources");patch({reader:false});}}><Database size={14}/>{t("map.sources")} {sources.length}</button>
            <button type="button" aria-pressed={route.query.reader} data-testid="map-open-reader" onClick={()=>openPage(selectedPage.id,true)}><BookOpen size={14}/>{t("map.read")}</button>
          </div>
          <div className="focusMapSelection" aria-label={t("map.selected")}>
            {!selectedVisible&&<p>{t("map.selectionOutside")}</p>}
            <div className="focusMapSelectionActions"><button type="button" data-testid="center-current" onClick={focusCurrent}><Focus size={15}/>{t("map.focusCurrent")}</button>
              {scope==="focus"&&<button type="button" data-testid="expand-current" disabled={!expandable?.hiddenNeighborCount||model.counts.shownNodes>=model.nodeBudget} onClick={()=>patch({mapExpanded:[...route.query.mapExpanded,selectedPage.id]})}>{t("map.expand")}{expandable?.hiddenNeighborCount?` (+${expandable.hiddenNeighborCount})`:""}</button>}
              {model.expandedIds.length>0&&<button type="button" data-testid="reset-expansion" onClick={()=>patch({mapExpanded:[],mapEdge:null})}>{t("map.collapse")}</button>}
            </div>
          </div>
          {route.query.reader ? <section className="focusMapReader" data-testid="focus-reader" aria-label={t("map.canonical")}>
            <div className="focusMapReaderLabel"><span>{t("map.canonical")} · {t("map.sourceCount",{n:sources.length})}</span><code>{selectedPage.path}</code></div>
            <Suspense fallback={<p role="status">{t("map.canonical")}…</p>}><PageReader bundle={bundle} pageId={selectedPage.id} demo={route.demo} snapshotSource={runtime.snapshotBase} loadPageContent={loadPageContent} embedded trail={[]} packetIds={route.query.packet} activeCenterId={route.query.center||null} onNavigatePage={key=>openPage(key,true)} onClose={closeReader} onTogglePacket={id=>patch({packet:route.query.packet.includes(id)?route.query.packet.filter(value=>value!==id):[...route.query.packet,id]})} onSnapshotMismatch={onSnapshotMismatch}/></Suspense>
            <div className="focusMapReaderReturn"><button type="button" onClick={()=>restoreFocus(readerOpener.current)}><ArrowLeft size={15}/>{t("map.back")}</button></div>
          </section> : <div className="focusMapPageSummary">
            {panelTab==="sources" ? <section className="focusMapSources"><h3>{t("map.sources")} ({sources.length})</h3>{sources.length ? <ul>{sources.map(ref=><li key={ref}>{renderReference(ref)}</li>)}</ul> : <p>{t("map.noSources")}</p>}
              {selectedPage.page_type==="source"&&<><h3>{t("map.citedBy")} ({citations.length})</h3>{citations.length ? <ul>{citations.map(({key,edge})=><li key={key}>{renderReference(edge.source)}</li>)}</ul> : <p>{t("map.noCitations")}</p>}</>}
            </section> : <><p>{selectedPage.summary||t("map.noSummary")}</p>{selectedPage.page_type==="source"&&<p className="focusMapSourceNotice"><Database size={16}/>{t("map.connectedSource")}</p>}<code className="focusMapOriginPath">{selectedPage.path}</code>{relations}</>}
          </div>}
        </> : <div className="focusMapReaderEmpty"><GitBranch size={28} aria-hidden="true"/><span className="focusMapEyebrow">{t("map.context")}</span><h2>{t("map.inspectTitle")}</h2><p>{t("map.inspectBody")}</p><div className="focusMapGuideStep"><span>1</span><p>{t("map.all")}</p></div><div className="focusMapGuideStep"><span>2</span><p>{t("map.focus")}</p></div><div className="focusMapGuideStep"><span>3</span><p>{t("map.sources")} · {t("map.read")}</p></div></div>}
        <footer className="focusMapSnapshot"><span>{t("map.snapshot")}</span><details><summary>Snapshot</summary><code>{bundle.manifest.snapshot_id}</code></details></footer>
      </aside>
    </div>
    {notice&&<p className="focusMapNotice" role="status">{notice}</p>}
    <span className="focusMapSrOnly" role="status">{selectedPage?.title||t("map.all")}. {t("map.counts",{shown:model.counts.shownNodes,total:model.counts.totalNodes,edges:model.counts.shownEdges,totalEdges:model.counts.totalEdges})}</span>
  </main>;
}
