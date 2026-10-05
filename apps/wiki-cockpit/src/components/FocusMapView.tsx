import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { NavigationPort, OperatorPort } from "../application/ports";
import type { RuntimeConfig } from "../data/runtimeConfig";
import { contextLabel, pageTypeLabel } from "../data/presentation";
import { t } from "../data/i18n";
import { localizedEncodingText, visualEncodingResolver } from "../data/visualEncoding";
import type { WorldPatch, WorldRoute } from "../router";
import { buildFocusMap, focusColorToken } from "../scene/focusMap";
import { searchPages } from "../scene/search";
import type { GraphNode, PageRecord, SnapshotBundle } from "../types";
import type { OverlayId } from "../world/contracts";
import { AppearanceControl } from "./AppearanceControl";
import "./focus-map.css";

const PageReader = lazy(() => import("./PageReader").then((module) => ({ default: module.PageReader })));

const OVERLAYS: OverlayId[] = ["attention", "freshness", "actions", "ownership", "evidence", "quality"];
const RESULT_LIMIT = 100;

type Props = {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  navigation: NavigationPort;
  loadPageContent: OperatorPort["loadPageContent"];
  onSnapshotMismatch?: () => void;
};

/** An opt-in, read-only projection of the existing versioned snapshot. */
export function FocusMapView({ bundle, runtime, route, navigation, loadPageContent, onSnapshotMismatch }: Props) {
  const pages = bundle.pages.pages;
  const pageIndex = useMemo(() => new Map(pages.flatMap((page) => [[page.id, page], [page.path, page]])), [pages]);
  const nodes = useMemo(() => new Map(bundle.graph.nodes.map((node) => [node.id, node])), [bundle.graph.nodes]);
  const selectedPage = pageIndex.get(route.query.page || route.pageId || "");
  const requestedFocus = route.query.mapFocus || selectedPage?.id || route.query.center || bundle.manifest.root_page_id || "";
  const focusId = nodes.has(requestedFocus) ? requestedFocus : bundle.graph.nodes[0]?.id || null;
  const model = useMemo(() => buildFocusMap(bundle.graph, {
    selectedId: focusId, expandedIds: route.query.mapExpanded
  }), [bundle.graph, focusId, route.query.mapExpanded]);
  const mode = route.query.mapMode || "graph";
  const colorMode = route.query.mapColor || "topic";
  const overlay: OverlayId = OVERLAYS.includes(route.query.overlay as OverlayId) ? route.query.overlay as OverlayId : "freshness";
  const focusPage = focusId ? pageIndex.get(focusId) : undefined;
  const selectedEdge = model.edges.find((edge) => edge.key === route.query.mapEdge);
  const search = useMemo(() => route.query.q.trim()
    ? searchPages(pages, route.query.q).hits
    : [...pages].sort((a, b) => a.title.localeCompare(b.title, "pt-BR") || a.id.localeCompare(b.id)), [pages, route.query.q]);
  const searchRef = useRef<HTMLInputElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);
  const readerSurfaceRef = useRef<HTMLElement>(null);
  const readerOpenerRef = useRef<HTMLElement | SVGElement | null>(null);
  const edgeOpenerRef = useRef<HTMLElement | SVGElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [notice, setNotice] = useState("");
  const patch = (value: WorldPatch, replace = false) => navigation.dispatch({ type: "patch-world", route, patch: value, replace });
  const restoreFocus = (opener: HTMLElement | SVGElement | null) => {
    window.requestAnimationFrame(() => {
      if (opener?.isConnected && !opener.closest("[inert]")) opener.focus();
      else searchRef.current?.focus();
    });
  };
  const activeElement = () => document.activeElement instanceof HTMLElement || document.activeElement instanceof SVGElement ? document.activeElement : null;
  const openEdge = (key: string) => {
    const opener = activeElement();
    if (opener && !opener.closest(".focusMapEdgeDetails")) edgeOpenerRef.current = opener;
    patch({ mapEdge: key });
  };
  const closeEdge = () => { patch({ mapEdge: null }); restoreFocus(edgeOpenerRef.current); };
  const goToReader = () => window.requestAnimationFrame(() => {
    readerSurfaceRef.current?.focus({ preventScroll: true });
    readerSurfaceRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
  });

  // Crafted URLs cannot open operator docks in this read-only projection.
  useEffect(() => {
    if (route.query.dock || route.query.tray || route.query.packView || (!route.query.mapFocus && focusId)) {
      navigation.dispatch({ type: "patch-world", route, patch: { dock: null, tray: null, packView: null,
        ...(!route.query.mapFocus && focusId ? { mapFocus: focusId } : {}) }, replace: true });
    }
  }, [focusId, navigation, route]);

  const openPage = (key: string, recenter = false) => {
    const page = pageIndex.get(key);
    if (!page) {
      setNotice(`Referência indisponível neste snapshot: ${key}`);
      return;
    }
    setNotice("");
    const opener = activeElement();
    if (opener && !opener.closest(".focusMapReader")) readerOpenerRef.current = opener;
    patch({ context: page.context || null, pageId: page.id, page: page.id, reader: true,
      mapFocus: recenter ? page.id : route.query.mapFocus || focusId,
      ...(recenter ? { mapExpanded: [], mapEdge: null } : {}), dock: null, tray: null, packView: null });
    if (window.matchMedia("(max-width: 1250px)").matches) goToReader();
  };
  const closeReader = () => { patch({ pageId: null, page: null, reader: false }); restoreFocus(readerOpenerRef.current); };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      if (surfaceRef.current?.querySelector(".pageReader.expanded")) return;
      const editing = (event.target as HTMLElement)?.closest?.("input, textarea, select, [contenteditable='true']");
      if (event.key === "/" && !editing) {
        event.preventDefault();
        searchRef.current?.focus();
      } else if (event.key === "Escape" && !editing && surfaceRef.current?.contains(event.target as Node)) {
        if (route.query.mapEdge) {
          event.preventDefault();
          closeEdge();
        } else if (route.query.reader) {
          event.preventDefault();
          closeReader();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const encodingFor = (node: GraphNode) => {
    if (colorMode === "state") {
      const encoding = visualEncodingResolver.resolve(node, overlay);
      return { color: encoding.color, label: localizedEncodingText(encoding), symbol: encoding.symbol, ring: encoding.ring };
    }
    const token = focusColorToken(node, colorMode);
    return { ...token, symbol: "", ring: "solid" };
  };
  const legend = colorMode === "state"
    ? visualEncodingResolver.legend(overlay, model.nodes.map((item) => item.node))
      .filter((entry) => entry.visibleCount > 0)
      .map((entry) => ({ key: entry.state, color: entry.color, label: `${entry.symbol} ${localizedEncodingText(entry)}`, count: entry.visibleCount }))
    : [...model.nodes.reduce((entries, item) => {
      const token = focusColorToken(item.node, colorMode);
      entries.set(token.key, { ...token, count: (entries.get(token.key)?.count || 0) + 1 });
      return entries;
    }, new Map<string, { key: string; color: string; label: string; count: number }>()).values()];
  const pageTitle = (id: string) => pageIndex.get(id)?.title || nodes.get(id)?.title || id;
  const related = selectedPage ? model.edges.filter(({ edge }) => edge.source === selectedPage.id || edge.target === selectedPage.id) : model.edges;
  const expandable = selectedPage && model.nodes.find((item) => item.id === selectedPage.id);
  const selectedVisible = selectedPage && model.nodes.some((item) => item.id === selectedPage.id);
  const canonicalHref = (page: PageRecord) => navigation.hrefForPatch(route, { context: page.context || null,
    pageId: page.id, page: page.id, reader: true, dock: null, tray: null, packView: null });

  return <main className="focusMap" data-testid="focus-map" ref={surfaceRef}>
    <header className="focusMapHeader">
      <div><span className="focusMapEyebrow">Wiki Viva · protótipo local</span><h1>Explorar conexões</h1></div>
      <div className="focusMapHeaderActions">
        <span className="focusMapReadOnly">{route.demo ? "Demo sintética · leitura" : "Snapshot · leitura"}</span>
        <AppearanceControl />
        <button type="button" onClick={() => patch({ projection: null, mapMode: null, mapFocus: null, mapExpanded: [], mapColor: null, mapEdge: null })}>Cockpit original ↗</button>
      </div>
    </header>
    <div className="focusMapBody">
      <aside className="focusMapSearch" aria-label="Busca e índice de páginas">
        <label htmlFor="focus-map-search">Encontrar um item <kbd>/</kbd></label>
        <input id="focus-map-search" data-testid="focus-search" ref={searchRef} type="search" value={route.query.q}
          placeholder="Título, resumo ou caminho…" onChange={(event) => patch({ q: event.target.value || null }, true)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && search[0]) { event.preventDefault(); openPage(search[0].id, true); }
            if (event.key === "ArrowDown") { event.preventDefault(); surfaceRef.current?.querySelector<HTMLElement>(".focusMapSearchResults button")?.focus(); }
          }} />
        <p className="focusMapSmall">{search.length} {route.query.q ? "resultados" : "itens no snapshot"} · busca nos metadados</p>
        <ul className="focusMapSearchResults">
          {search.slice(0, RESULT_LIMIT).map((page) => <li key={page.id}>
            <button type="button" aria-current={selectedPage?.id === page.id ? "page" : undefined}
              onClick={() => openPage(page.id, true)} data-page-id={page.id}>
              <strong>{page.title}</strong><span>{contextLabel(page.context)} · {pageTypeLabel(page.page_type)}</span>
            </button>
          </li>)}
        </ul>
        {!search.length && <p>Nenhum resultado. Tente outro título ou caminho.</p>}
        {search.length > RESULT_LIMIT && <p>Mostrando {RESULT_LIMIT}. Refine a busca para encontrar os demais.</p>}
        <p className="focusMapSnapshot">Snapshot <code>{bundle.manifest.snapshot_id}</code><br />As relações e a leitura vêm da mesma revisão.</p>
      </aside>

      <section className="focusMapExplorer" aria-label="Exploração de relações">
        <div className="focusMapToolbar">
          <div className="focusMapViewSwitch" role="group" aria-label="Visualização dos mesmos itens">
            <button type="button" data-testid="map-graph-mode" aria-pressed={mode === "graph"} onClick={() => patch({ mapMode: "graph" })}>Mapa</button>
            <button type="button" data-testid="map-list-mode" aria-pressed={mode === "list"} onClick={() => patch({ mapMode: "list" })}>Lista</button>
          </div>
          <label>Cor significa <select aria-label="Cor significa" value={colorMode} onChange={(event) => patch({ mapColor: event.target.value as "topic" | "category" | "state" })}>
            <option value="topic">Tema / área</option><option value="category">Categoria</option><option value="state">Estado</option>
          </select></label>
          {colorMode === "state" && <label>Métrica <select aria-label="Métrica de estado" value={overlay} onChange={(event) => patch({ overlay: event.target.value })}>
            {OVERLAYS.map((id) => <option value={id} key={id}>{t(`world.overlay.${id}`)}</option>)}
          </select></label>}
        </div>
        <div className="focusMapFocusHeading">
          <div><span className="focusMapEyebrow">Foco do mapa</span><h2>{focusPage?.title || pageTitle(focusId || "") || "Snapshot sem itens"}</h2></div>
          {model.expandedIds.length > 0 && <button type="button" data-testid="reset-expansion" onClick={() => patch({ mapExpanded: [], mapEdge: null })}>Recolher expansão</button>}
        </div>
        <p className="focusMapCounts" data-testid="focus-counts">{model.counts.shownNodes} de {model.counts.totalNodes} itens · {model.counts.shownEdges} de {model.counts.totalEdges} relações
          {model.counts.outsideFocusNodes > 0 && ` · ${model.counts.outsideFocusNodes} itens fora do foco`}
          {model.counts.hiddenCandidateNodes > 0 && ` · ${model.counts.hiddenCandidateNodes} itens além do limite de ${model.nodeBudget}`}
          {model.counts.unresolvedEdges > 0 && ` · ${model.counts.unresolvedEdges} relações com referência indisponível`}</p>
        {requestedFocus && requestedFocus !== focusId && <p role="status">Foco solicitado indisponível neste snapshot. Mostrando o primeiro item disponível.</p>}
        {model.ignoredExpansionIds.length > 0 && <p className="focusMapSmall">{model.ignoredExpansionIds.length} expansões indisponíveis ou fora deste foco.</p>}

        <div className="focusMapLegend" aria-label={`Legenda de ${colorMode === "state" ? `estado: ${t(`world.overlay.${overlay}`)}` : colorMode === "topic" ? "tema / área" : "categoria"}`}>
          <strong>{colorMode === "state" ? `Estado · ${t(`world.overlay.${overlay}`)}` : colorMode === "topic" ? "Tema / área" : "Categoria"}</strong>
          {legend.map((item) => <span key={item.key}><i style={{ backgroundColor: item.color }} aria-hidden="true" />{item.label} <small>{item.count}</small></span>)}
        </div>

        {mode === "graph" ? <>
          <div className="focusMapCanvasTools"><span>Clique em um item para ler; na linha, para verificar a relação.</span><div>
            <button type="button" aria-label="Reduzir mapa" disabled={zoom <= 0.75} onClick={() => setZoom((value) => Math.max(0.75, value - 0.25))}>−</button>
            <button type="button" aria-label="Ampliar mapa" disabled={zoom >= 2} onClick={() => setZoom((value) => Math.min(2, value + 0.25))}>+</button>
            <button type="button" onClick={() => setZoom(1)}>Ajustar</button></div></div>
          <div className="focusMapCanvas" tabIndex={0} aria-label="Mapa com rolagem; relações também disponíveis na lista abaixo">
            <svg data-testid="focus-svg" role="group" aria-label="Itens e relações do foco" viewBox={`${model.bounds.x} ${model.bounds.y} ${model.bounds.width} ${model.bounds.height}`}
              style={{ width: `${zoom * 100}%`, minWidth: `${zoom * 760}px` }}>
              <defs><marker id="focus-map-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs>
              {model.edges.map((item) => <g key={item.key} className={item.key === route.query.mapEdge ? "focusMapEdge selected" : "focusMapEdge"}>
                <path className="focusMapEdgeLine" d={item.path} markerEnd={item.directed === true ? "url(#focus-map-arrow)" : undefined} />
                <path d={item.path} className="focusMapEdgeHit" role="button" tabIndex={0} aria-pressed={item.key === route.query.mapEdge}
                  aria-label={`Relação ${item.edge.type}: ${pageTitle(item.edge.source)} ${item.directed === true ? "para" : "com"} ${pageTitle(item.edge.target)}`}
                  data-edge-key={item.key} data-edge-id={item.edge.id || ""} data-testid={`focus-edge-${item.edge.id || item.key}`}
                  onClick={() => openEdge(item.key)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openEdge(item.key); } }} />
                <text x={item.labelX} y={item.labelY + (item.laneCount > 1 ? (item.laneIndex - (item.laneCount - 1) / 2) * 25 : 0)} className="focusMapEdgeLabel" aria-hidden="true">{item.edge.type}</text>
              </g>)}
              {model.nodes.map((item) => {
                const encoding = encodingFor(item.node);
                return <foreignObject key={item.id} x={item.x - item.width / 2} y={item.y - item.height / 2} width={item.width} height={item.height}>
                  <button type="button" className={`focusMapNode${item.id === selectedPage?.id ? " selected" : ""}${item.id === focusId ? " focal" : ""}`}
                    style={{ "--focus-map-data-color": encoding.color } as CSSProperties} data-ring={encoding.ring}
                    data-testid={`focus-node-${item.id}`} aria-pressed={item.id === selectedPage?.id} onClick={() => openPage(item.id)}>
                    <span className="focusMapNodeMeta">{item.id === focusId ? "◎ " : ""}{pageTypeLabel(item.node.page_type)}{item.isExpanded && item.id !== focusId ? " · expandido" : ""}</span>
                    <strong>{item.label}</strong><span>{encoding.symbol ? `${encoding.symbol} ` : ""}{encoding.label}</span>
                  </button>
                </foreignObject>;
              })}
            </svg>
          </div>
        </> : <ul className="focusMapItemList" aria-label="Itens do mesmo foco">
          {model.nodes.map((item) => {
            const encoding = encodingFor(item.node);
            const page = pageIndex.get(item.id);
            return <li key={item.id}><button type="button" onClick={() => openPage(item.id)} aria-current={selectedPage?.id === item.id ? "page" : undefined}>
              <i aria-hidden="true" style={{ backgroundColor: encoding.color }} /><div><strong>{item.label}</strong><span>{pageTypeLabel(item.node.page_type)} · {contextLabel(item.node.context)} · {encoding.symbol} {encoding.label}</span>
                {page?.summary && <p>{page.summary}</p>}</div><span aria-hidden="true">→</span></button></li>;
          })}
        </ul>}

        <section className="focusMapSelection" aria-label="Item selecionado e próximos passos de exploração">
          <div><strong>{selectedPage ? `Selecionado: ${selectedPage.title}` : "Selecione um item para ler e explorar"}</strong>
            {selectedPage && !selectedVisible && <span>Fora do foco atual.</span>}</div>
          {selectedPage && <div className="focusMapSelectionActions">
            <button type="button" data-testid="center-current" disabled={focusId === selectedPage.id && model.expandedIds.length === 0}
              onClick={() => { setZoom(1); patch({ mapFocus: selectedPage.id, mapExpanded: [], mapEdge: null }); }}>Focar neste item</button>
            <button type="button" data-testid="expand-current" disabled={!expandable || expandable.hiddenNeighborCount === 0 || model.counts.shownNodes >= model.nodeBudget}
              onClick={() => patch({ mapExpanded: [...route.query.mapExpanded, selectedPage.id], mapEdge: null })}>Expandir relações{expandable?.hiddenNeighborCount ? ` (+${expandable.hiddenNeighborCount})` : ""}</button>
            <button type="button" onClick={() => route.query.reader ? goToReader() : openPage(selectedPage.id)}>{route.query.reader ? "Ir para leitura" : "Abrir leitor"}</button>
          </div>}
          {model.counts.shownNodes >= model.nodeBudget && <p className="focusMapSmall">Limite de {model.nodeBudget} itens neste recorte. Foque em outro item para continuar a exploração.</p>}
        </section>

        {route.query.mapEdge && <aside className="focusMapEdgeDetails" data-testid="focus-edge-details" aria-label="Detalhes da relação">
          <div className="focusMapSectionHeading"><h3>{selectedEdge ? `Relação · ${selectedEdge.edge.type}` : "Relação indisponível neste recorte"}</h3><button type="button" aria-label="Fechar detalhes da relação" onClick={closeEdge}>×</button></div>
          {selectedEdge && <>
            <p className="focusMapEdgeEndpoints"><button type="button" onClick={() => openPage(selectedEdge.edge.source)}>{pageTitle(selectedEdge.edge.source)}</button>
              <span>{selectedEdge.directed === true ? "→" : selectedEdge.directed === false ? "↔" : "—"}</span>
              <button type="button" onClick={() => openPage(selectedEdge.edge.target)}>{pageTitle(selectedEdge.edge.target)}</button></p>
            <dl><dt>Direção</dt><dd>{selectedEdge.edge.direction || "Não registrada"}</dd>
              <dt>Observada em</dt><dd>{selectedEdge.edge.observed_at || "Não registrado"}</dd>
              <dt>Base</dt><dd>{selectedEdge.edge.basis || "Não registrada"}</dd>
              <dt>Estado da relação</dt><dd>{selectedEdge.edge.status || "Não registrado"}</dd></dl>
            <h4>Proveniência registrada</h4>
            {selectedEdge.edge.provenance && Object.keys(selectedEdge.edge.provenance).length ? <dl>{Object.entries(selectedEdge.edge.provenance).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{value}</code></dd></div>)}</dl> : <p>Não registrada no snapshot.</p>}
            {(() => { const origin = pageIndex.get(selectedEdge.edge.provenance?.page_id || selectedEdge.edge.provenance?.path || "");
              return origin ? <a href={canonicalHref(origin)}>Ler página que registra esta relação ↗</a> : null; })()}
            {selectedEdge.laneCount > 1 && <p className="focusMapSmall">{selectedEdge.laneCount} relações distintas entre estes itens; cada linha conserva seu registro.</p>}
          </>}
        </aside>}

        <details className="focusMapRelations" open><summary>Relações {selectedPage ? "do item selecionado" : "neste foco"} ({related.length})</summary>
          <p className="focusMapSmall">Linhas neutras: o texto indica o tipo; a seta indica direção registrada. Use Tab e Enter para inspecionar.</p>
          <ul aria-label="Lista acessível de relações">{related.map((item) => <li key={item.key}>
            <button type="button" data-edge-id={item.edge.id || ""} aria-pressed={route.query.mapEdge === item.key} onClick={() => openEdge(item.key)}>
              <code>{item.edge.type}</code><span>{pageTitle(item.edge.source)} {item.directed === true ? "→" : item.directed === false ? "↔" : "—"} {pageTitle(item.edge.target)}</span></button>
          </li>)}</ul>
          {selectedPage && <p className="focusMapSmall">Lista restrita às relações exibidas. O leitor inclui referências canônicas, inclusive as indisponíveis.</p>}
        </details>
        {notice && <p className="focusMapNotice" role="status">{notice}</p>}
        <span className="focusMapSrOnly" role="status">{selectedPage ? `Selecionado ${selectedPage.title}` : "Nenhum item selecionado"}. {model.counts.shownNodes} itens e {model.counts.shownEdges} relações no foco.</span>
      </section>

      {selectedPage && route.query.reader ? <section className="focusMapReader" data-testid="focus-reader" ref={readerSurfaceRef} tabIndex={-1} aria-label={`Leitura canônica e fontes: ${selectedPage.title}`}>
        <div className="focusMapReaderLabel"><span>Leitura canônica · {selectedPage.source_refs.length} referências de fonte</span><code>{selectedPage.path}</code></div>
        <Suspense fallback={<p role="status">Abrindo leitura canônica…</p>}><PageReader bundle={bundle} pageId={selectedPage.id} demo={route.demo} snapshotSource={runtime.snapshotBase}
          loadPageContent={loadPageContent} embedded trail={[]} packetIds={route.query.packet}
          activeCenterId={route.query.center || null} onNavigatePage={(key) => openPage(key)} onClose={closeReader}
          onTogglePacket={(id) => patch({ packet: route.query.packet.includes(id) ? route.query.packet.filter((value) => value !== id) : [...route.query.packet, id] })}
          onSnapshotMismatch={onSnapshotMismatch} /></Suspense>
        <div className="focusMapReaderReturn"><button type="button" onClick={() => restoreFocus(readerOpenerRef.current)}>Voltar à exploração</button></div>
      </section> : <aside className="focusMapReaderEmpty"><span className="focusMapEyebrow">Leitor e fontes</span><h2>Da conexão ao contexto</h2>
        <p>Selecione um item. Aqui você lê a página canônica, confere o caminho e segue suas fontes.</p><p>O mapa é uma projeção do snapshot: a seleção e a expansão não alteram a wiki.</p></aside>}
    </div>
  </main>;
}
