import type { GraphEdge, GraphNode } from "../types";
import { keyEdges, type FocusGraph, type KeyedEdge } from "./focusMap";

export type MapPerspective = "network" | "areas" | "evidence" | "work";
export type MapPoint = { x: number; y: number };
export type MapBounds = MapPoint & { width: number; height: number };
export const MAP_NODE_BUDGET = 180;
export const MAP_FOCUS_BUDGET = 64;
export const MAP_EDGE_BUDGET = 900;

export type IntegratedGraph = {
  nodes: Map<string, GraphNode>;
  edges: KeyedEdge[];
  edgeByKey: Map<string, KeyedEdge>;
  neighbors: Map<string, Set<string>>;
  incident: Map<string, KeyedEdge[]>;
  unresolvedEdges: number;
};

export type IntegratedMapNode = {
  id: string; node: GraphNode; group: string; point: MapPoint;
  depth: number; hiddenNeighborCount: number; labelPriority: boolean;
};
export type IntegratedMap = {
  nodes: IntegratedMapNode[];
  edges: (KeyedEdge & { lane: number; laneCount: number })[];
  groups: { key: string; x: number; y: number; count: number }[];
  bounds: MapBounds;
  expandedIds: string[];
  ignoredExpansionIds: string[];
  nodeBudget: number;
  counts: {
    totalNodes: number; shownNodes: number; candidateNodes: number;
    hiddenCandidateNodes: number; outsideFocusNodes: number;
    totalEdges: number; shownEdges: number; omittedEdges: number; unresolvedEdges: number;
  };
};

const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
const round = (n: number) => Math.round(n * 1000) / 1000;
const unique = (ids: readonly string[]) => [...new Set(ids)].sort(compare);

/** Index a revision once. Every edge retains the exact original record. */
export function indexIntegratedGraph(graph: FocusGraph): IntegratedGraph {
  const nodes = new Map([...graph.nodes].sort((a, b) => compare(a.id, b.id)).map(node => [node.id, node]));
  const edges = keyEdges(graph.edges);
  const neighbors = new Map([...nodes.keys()].map(id => [id, new Set<string>()]));
  const incident = new Map([...nodes.keys()].map(id => [id, [] as KeyedEdge[]]));
  let unresolvedEdges = 0;
  for (const record of edges) {
    const {source, target} = record.edge;
    incident.get(source)?.push(record);
    if (source !== target) incident.get(target)?.push(record);
    if (!nodes.has(source) || !nodes.has(target)) { unresolvedEdges++; continue; }
    if (source !== target) {
      neighbors.get(source)!.add(target);
      neighbors.get(target)!.add(source);
    }
  }
  return {nodes, edges, edgeByKey:new Map(edges.map(edge => [edge.key, edge])), neighbors, incident, unresolvedEdges};
}

function groupFor(node: GraphNode, perspective: MapPerspective): string {
  if (perspective === "network" || perspective === "areas") return node.context || "";
  if (perspective === "evidence") {
    if (node.page_type === "source" || node.page_type === "ingestion_event") return "sources";
    if (["claim", "artifact", "insight"].includes(node.page_type)) return "knowledge";
    if (["decision", "action", "project"].includes(node.page_type)) return "work";
    return "context";
  }
  if (node.page_type === "decision") return "decisions";
  if (node.page_type === "action") return "actions";
  if (["project", "dashboard"].includes(node.page_type)) return "projects";
  return "context";
}

function layout(nodes: GraphNode[], edges: KeyedEdge[], perspective: MapPerspective, focus: string | null, focused: boolean) {
  const grouped = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    const key = groupFor(node, perspective);
    grouped.set(key, [...(grouped.get(key) || []), node]);
  }
  const keys = [...grouped.keys()].sort(compare);
  const centers = new Map<string, MapPoint>();
  keys.forEach((key, index) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / Math.max(1, keys.length);
    centers.set(key, keys.length === 1 ? {x:800,y:520} : {x:800+Math.cos(angle)*510,y:520+Math.sin(angle)*320});
  });
  const points = new Map<string, MapPoint>();
  const anchors = new Map<string, MapPoint>();
  for (const [key, members] of grouped) {
    const center = centers.get(key)!;
    members.forEach((node,index) => {
      const angle = index * Math.PI * (3 - Math.sqrt(5));
      const radius = 42 * Math.sqrt(index);
      const point = {x:center.x+Math.cos(angle)*radius,y:center.y+Math.sin(angle)*radius};
      points.set(node.id, point); anchors.set(node.id, {...point});
    });
  }
  if (focused && (nodes.length<=12 || perspective === "network" || perspective === "areas") && focus) {
    const others = nodes.filter(node => node.id !== focus).sort((a,b)=>compare(groupFor(a,perspective),groupFor(b,perspective))||compare(a.id,b.id));
    points.set(focus,{x:800,y:520}); anchors.set(focus,{x:800,y:520});
    others.forEach((node,index) => {
      const angle = -Math.PI/2 + index * Math.PI*2/Math.max(1,others.length);
      const radius = others.length <= 12 ? 300 : 300+80*Math.floor(index/12);
      const point = {x:800+Math.cos(angle)*radius*1.45,y:520+Math.sin(angle)*radius};
      points.set(node.id,point); anchors.set(node.id,{...point});
    });
  } else if (perspective === "network") {
    const center = nodes.find(node => node.id === focus && node.page_type === "root_entity");
    if (center) { points.set(center.id,{x:800,y:520}); anchors.set(center.id,{x:800,y:520}); }
  }
  // A finite deterministic relaxation, never a simulation running while idle.
  // Pair work is bounded by 180 nodes; grouping/selection does not invent edges.
  {
    const degree = new Map(nodes.map(node => [node.id, 0]));
    edges.forEach(({edge}) => { degree.set(edge.source,(degree.get(edge.source)||0)+1); degree.set(edge.target,(degree.get(edge.target)||0)+1); });
    for (let iteration=0;iteration<(perspective==="network"?36:18);iteration++) {
      for (let a=0;a<nodes.length;a++) for (let b=a+1;b<nodes.length;b++) {
        const first=points.get(nodes[a].id)!, second=points.get(nodes[b].id)!;
        let dx=second.x-first.x, dy=second.y-first.y;
        if (!dx && !dy) dx=1;
        const distance=Math.max(1,Math.hypot(dx,dy));
        if (distance >= 100) continue;
        const force=(100-distance)*.28;
        dx=dx/distance*force; dy=dy/distance*force;
        first.x-=dx;first.y-=dy;second.x+=dx;second.y+=dy;
      }
      for (const {edge} of perspective==="network"?edges:[]) {
        if (edge.source===edge.target) continue;
        const a=points.get(edge.source)!,b=points.get(edge.target)!;
        const dx=b.x-a.x,dy=b.y-a.y,distance=Math.max(1,Math.hypot(dx,dy));
        const force=Math.max(-5,Math.min(5,(distance-220)*.018));
        const ax=dx/distance*force,ay=dy/distance*force;
        a.x+=ax/Math.sqrt(degree.get(edge.source)||1);a.y+=ay/Math.sqrt(degree.get(edge.source)||1);
        b.x-=ax/Math.sqrt(degree.get(edge.target)||1);b.y-=ay/Math.sqrt(degree.get(edge.target)||1);
      }
      for (const node of nodes) {
        const point=points.get(node.id)!,anchor=anchors.get(node.id)!;
        point.x+=(anchor.x-point.x)*.12;point.y+=(anchor.y-point.y)*.12;
      }
    }
  }
  for (const point of points.values()) {point.x=round(point.x);point.y=round(point.y);}
  return {points, groups:keys.map(key => {
    const members=grouped.get(key)!;
    const x=members.reduce((sum,node)=>sum+points.get(node.id)!.x,0)/members.length;
    const y=Math.min(...members.map(node=>points.get(node.id)!.y))-72;
    return {key,x:round(x),y:round(y),count:members.length};
  })};
}

export function buildIntegratedMap(index: IntegratedGraph, options: {
  focusId: string | null; selectedId?: string | null; selectedEdge?: string;
  scope: "all" | "focus"; perspective: MapPerspective; expandedIds?: readonly string[];
}): IntegratedMap {
  const {nodes, neighbors}=index;
  const focus=options.focusId && nodes.has(options.focusId) ? options.focusId : null;
  const expanded=unique(options.expandedIds||[]).slice(0,64);
  const depths=new Map<string,number>();
  if (options.scope === "focus") {
    const queue=focus?[focus]:[];
    const queued=new Set(queue);
    if (focus) depths.set(focus,0);
    for (let cursor=0;cursor<queue.length;cursor++) {
      const id=queue[cursor];
      for (const next of unique([...neighbors.get(id)!])) {
        if (!depths.has(next)) depths.set(next,depths.get(id)!+1);
        if (expanded.includes(next) && !queued.has(next)) {queue.push(next);queued.add(next);}
      }
    }
  } else for (const id of nodes.keys()) depths.set(id,0);
  const budget=options.scope === "focus"?MAP_FOCUS_BUDGET:MAP_NODE_BUDGET;
  const chosen=new Set<string>();
  const pin=(id:string|null|undefined)=>{if(id && depths.has(id) && chosen.size<budget) chosen.add(id);};
  pin(focus);
  if (options.scope === "all") {
    pin(options.selectedId);
    const edge=options.selectedEdge?index.edgeByKey.get(options.selectedEdge)?.edge:undefined;
    pin(edge?.source);pin(edge?.target);
    // Keep real area anchors represented in large overviews, then traverse
    // their actual adjacency. Disconnected components remain disconnected.
    for (const node of nodes.values()) if (["root_entity","context_hub"].includes(node.page_type)) pin(node.id);
    const queue=[...chosen];
    for (let cursor=0;cursor<queue.length && chosen.size<budget;cursor++) {
      for (const id of unique([...neighbors.get(queue[cursor])!])) {
        if(chosen.size>=budget)break;
        if (!chosen.has(id)) {pin(id);queue.push(id);}
      }
    }
  }
  for (const id of [...depths.keys()].sort((a,b)=>depths.get(a)!-depths.get(b)!||compare(a,b))) pin(id);
  const shown=[...chosen].sort(compare).map(id=>nodes.get(id)!);
  const candidates=index.edges.filter(({edge})=>chosen.has(edge.source)&&chosen.has(edge.target));
  const edges=[...candidates].sort((a,b)=>Number(b.key===options.selectedEdge)-Number(a.key===options.selectedEdge)||compare(a.key,b.key)).slice(0,MAP_EDGE_BUDGET);
  const positioned=layout(shown,edges,options.perspective,focus,options.scope==="focus");
  const pairs=new Map<string,KeyedEdge[]>();
  for (const edge of edges) {
    const pair=JSON.stringify([edge.edge.source,edge.edge.target].sort(compare));
    pairs.set(pair,[...(pairs.get(pair)||[]),edge]);
  }
  const lanes=new Map<string,{lane:number;laneCount:number}>();
  for (const pair of pairs.values()) pair.sort((a,b)=>compare(a.key,b.key)).forEach((edge,i)=>lanes.set(edge.key,{lane:i-(pair.length-1)/2,laneCount:pair.length}));
  const priorities=[...shown].sort((a,b)=>Number(b.id===focus)-Number(a.id===focus)||Number(b.page_type==="context_hub")-Number(a.page_type==="context_hub")||(neighbors.get(b.id)?.size||0)-(neighbors.get(a.id)?.size||0)||compare(a.id,b.id));
  const labels=new Set(priorities.slice(0,28).map(node=>node.id));
  const output=shown.map(node=>({id:node.id,node,group:groupFor(node,options.perspective),point:positioned.points.get(node.id)!,depth:depths.get(node.id)!,hiddenNeighborCount:[...neighbors.get(node.id)!].filter(id=>!chosen.has(id)).length,labelPriority:labels.has(node.id)}));
  const drawn=edges.map(edge=>({...edge,...lanes.get(edge.key)!}));
  const hulls=drawn.map(item=>integratedEdgeGeometry(item.edge,item.lane,positioned.points.get(item.edge.source)!,positioned.points.get(item.edge.target)!).bounds);
  const xs=[...output.map(node=>node.point.x),...hulls.flatMap(hull=>[hull.x,hull.x+hull.width])];
  const ys=[...output.map(node=>node.point.y),...hulls.flatMap(hull=>[hull.y,hull.y+hull.height])];
  const x=xs.length?Math.min(...xs)-140:0,y=ys.length?Math.min(...ys)-105:0;
  return {
    nodes:output,edges:drawn,groups:positioned.groups,
    bounds:{x,y,width:xs.length?Math.max(...xs)-x+140:1200,height:ys.length?Math.max(...ys)-y+110:800},
    expandedIds:expanded.filter(id=>chosen.has(id)&&id!==focus),ignoredExpansionIds:expanded.filter(id=>!depths.has(id)),nodeBudget:budget,
    counts:{totalNodes:nodes.size,shownNodes:chosen.size,candidateNodes:depths.size,hiddenCandidateNodes:depths.size-chosen.size,outsideFocusNodes:nodes.size-depths.size,totalEdges:index.edges.length,shownEdges:edges.length,omittedEdges:index.edges.length-edges.length,unresolvedEdges:index.unresolvedEdges}
  };
}

/** Separate curves for parallel, reciprocal and self relations. */
export function integratedEdgeGeometry(edge: GraphEdge, lane: number, source: MapPoint, target: MapPoint, radius=27) {
  if (edge.source===edge.target) {
    const side=lane<0?1:-1;
    const rise=65+Math.abs(lane)*32/(1+Math.abs(lane)*.2);
    const y=source.y+side*rise,tip=source.y+side*13;
    return {path:`M ${source.x+13} ${tip} C ${source.x+90} ${y} ${source.x-90} ${y} ${source.x-13} ${tip}`,x:source.x,y:source.y+side*rise*.74,
      bounds:{x:source.x-90,y:Math.min(y,tip),width:180,height:Math.abs(y-tip)}};
  }
  const dx=target.x-source.x,dy=target.y-source.y,distance=Math.max(1,Math.hypot(dx,dy));
  // Fixed screen-size markers can be wider than a short zoomed-out edge.
  // Keep start before end and the final tangent toward the recorded target.
  const inset=Math.min(radius,distance*.4);
  const sign=compare(edge.source,edge.target)<0?1:-1;
  // Monotonic bounded lanes keep dense relations distinct without sending
  // curves thousands of units off the map. Every record remains inspectable.
  const offset=lane*54*sign/(1+Math.abs(lane)*.18);
  const control={x:(source.x+target.x)/2-dy/distance*offset,y:(source.y+target.y)/2+dx/distance*offset};
  const start={x:source.x+dx/distance*inset,y:source.y+dy/distance*inset};
  const end={x:target.x-dx/distance*inset,y:target.y-dy/distance*inset};
  const x=Math.min(start.x,control.x,end.x),y=Math.min(start.y,control.y,end.y);
  return {path:`M ${round(start.x)} ${round(start.y)} Q ${round(control.x)} ${round(control.y)} ${round(end.x)} ${round(end.y)}`,x:(start.x+2*control.x+end.x)/4,y:(start.y+2*control.y+end.y)/4,
    bounds:{x,y,width:Math.max(start.x,control.x,end.x)-x,height:Math.max(start.y,control.y,end.y)-y}};
}

export function fitMapCamera(bounds: MapBounds, viewport: {width:number;height:number}) {
  // Reserve the bottom tool strip in the same viewport used for pan/zoom.
  // A fit must not place a selectable page behind camera controls.
  const height=Math.max(1,viewport.height-52);
  const scale=Math.max(.05,Math.min(1.6,viewport.width/bounds.width,height/bounds.height)*.93);
  return {x:viewport.width/2-(bounds.x+bounds.width/2)*scale,y:height/2-(bounds.y+bounds.height/2)*scale,scale};
}
