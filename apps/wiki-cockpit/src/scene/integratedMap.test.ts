import {readFileSync} from "node:fs";
import {describe,expect,it} from "vitest";
import type {GraphEdge,GraphNode} from "../types";
import {buildIntegratedMap,fitMapCamera,indexIntegratedGraph,integratedEdgeGeometry,MAP_EDGE_BUDGET,MAP_NODE_BUDGET} from "./integratedMap";
import type {MapPerspective} from "./integratedMap";

const full=JSON.parse(readFileSync(new URL("../../public/sample-snapshot/graph.json",import.meta.url),"utf8")) as {nodes:GraphNode[];edges:GraphEdge[]};
const small=JSON.parse(readFileSync(new URL("../../public/sample-snapshot/scenarios/walking_skeleton/graph.json",import.meta.url),"utf8")) as typeof full;
const options={focusId:"root-alex-rivera",scope:"all" as const,perspective:"network" as const};
const node=(id:string):GraphNode=>({id,path:`memories/${id}.md`,title:id,page_type:"claim",context:"example",freshness_state:"unknown",approved_state:"approved",risk_flags:[],metrics:{inbound_links:0,outbound_links:0,source_ref_count:0}});
const edge=(source:string,target:string,id:string):GraphEdge=>({source,target,id,type:"source_ref",status:"valid",weight:1,direction:"directed",provenance:{page_id:source,path:`memories/${source}.md`,field:"source_refs"}});

describe("connected revision projection",()=>{
  it("shows the full public overview and preserves every original record across perspectives",()=>{
    const before=JSON.stringify(full),index=indexIntegratedGraph(full);
    for(const perspective of ["network","areas","evidence","work"] as MapPerspective[]) {
      const result=buildIntegratedMap(index,{...options,perspective});
      expect(result.counts).toMatchObject({totalNodes:107,shownNodes:107,totalEdges:148,shownEdges:148,unresolvedEdges:0});
      expect(result.nodes.map(item=>item.id)).toEqual([...index.nodes.keys()]);
      expect(result.edges.map(item=>item.key).sort()).toEqual(index.edges.map(item=>item.key).sort());
      result.edges.forEach(item=>expect(item.edge).toBe(index.edgeByKey.get(item.key)!.edge));
    }
    expect(JSON.stringify(full)).toBe(before);
  });
  it("produces the same layout from reordered input and actually changes geometry with perspective",()=>{
    const original=buildIntegratedMap(indexIntegratedGraph(full),options);
    const reversed=buildIntegratedMap(indexIntegratedGraph({nodes:[...full.nodes].reverse(),edges:[...full.edges].reverse()}),options);
    expect(reversed).toEqual(original);
    const areas=buildIntegratedMap(indexIntegratedGraph(full),{...options,perspective:"areas"});
    expect(areas.nodes.map(item=>item.point)).not.toEqual(original.nodes.map(item=>item.point));
    expect(areas.edges.map(item=>item.key).sort()).toEqual(original.edges.map(item=>item.key).sort());
  });
  it("expands only real reachable adjacency and retains a separate global overview",()=>{
    const index=indexIntegratedGraph(small),focus={focusId:"source-banco-export",scope:"focus" as const,perspective:"network" as const};
    const first=buildIntegratedMap(index,focus);
    expect(first.nodes.map(item=>item.id).sort()).toEqual(["artifact-relatorio-recon","claim-custos-sobem","event-ingest-banco-2026-05","hub-financeiro","source-banco-export"]);
    expect(first.edges).toHaveLength(10);
    const skipped=buildIntegratedMap(index,{...focus,expandedIds:["root-alex-rivera","missing"]});
    expect(skipped.nodes).toEqual(first.nodes);expect(skipped.ignoredExpansionIds).toEqual(["missing","root-alex-rivera"]);
    const expanded=buildIntegratedMap(index,{...focus,expandedIds:["hub-financeiro","root-alex-rivera"]});
    expect(expanded.nodes).toHaveLength(7);expect(expanded.counts.outsideFocusNodes).toBe(1);
    expect(buildIntegratedMap(index,{...focus,scope:"all"}).nodes).toHaveLength(8);
  });
  it("keeps parallel, reciprocal, self and unknown-direction edges separate",()=>{
    const graph={nodes:[node("a"),node("b")],edges:[edge("a","b","ab"),edge("b","a","ba"),{...edge("a","b","ab2"),direction:undefined},{...edge("a","a","self"),direction:"undirected"}]};
    const index=indexIntegratedGraph(graph),result=buildIntegratedMap(index,{...options,focusId:"a"});
    expect(result.edges).toHaveLength(4);expect(new Set(result.edges.map(item=>item.key)).size).toBe(4);
    const points=new Map(result.nodes.map(item=>[item.id,item.point]));
    const paths=result.edges.map(item=>integratedEdgeGeometry(item.edge,item.lane,points.get(item.edge.source)!,points.get(item.edge.target)!).path);
    expect(new Set(paths).size).toBe(4);expect(result.edges.find(item=>item.edge.id==="ab2")!.edge.direction).toBeUndefined();
    expect(index.incident.get("a")).toHaveLength(4);
  });
  it("retains unavailable endpoint records in the inspector without drawing a fabricated node",()=>{
    const record=edge("a","missing","gap"),index=indexIntegratedGraph({nodes:[node("a")],edges:[record]});
    const result=buildIntegratedMap(index,{...options,focusId:"a"});
    expect(result.counts).toMatchObject({totalEdges:1,shownEdges:0,unresolvedEdges:1});
    expect(index.incident.get("a")![0].edge).toBe(record);expect(result.nodes.map(item=>item.id)).toEqual(["a"]);
  });
  it("bounds large graph drawing and pins selected pages and edge endpoints",()=>{
    const nodes=Array.from({length:10000},(_,i)=>node(`node-${String(i).padStart(5,"0")}`));
    const edges=nodes.slice(1).map((item,i)=>edge(nodes[i].id,item.id,`edge-${i}`));
    const index=indexIntegratedGraph({nodes,edges}),selected=index.edges.find(item=>item.edge.id==="edge-9998")!;
    const result=buildIntegratedMap(index,{...options,focusId:nodes[0].id,selectedId:nodes[5000].id,selectedEdge:selected.key});
    expect(result.nodes).toHaveLength(MAP_NODE_BUDGET);expect(result.edges.length).toBeLessThanOrEqual(MAP_EDGE_BUDGET);
    expect(result.nodes.map(item=>item.id)).toEqual(expect.arrayContaining([nodes[0].id,nodes[5000].id,nodes[9998].id,nodes[9999].id]));
    expect(result.edges.map(item=>item.key)).toContain(selected.key);expect(result.counts.hiddenCandidateNodes).toBe(10000-MAP_NODE_BUDGET);
    expect(result.counts.totalEdges).toBe(9999);
  });
  it("caps dense parallel edges while keeping all original records queryable",()=>{
    const index=indexIntegratedGraph({nodes:[node("a"),node("b")],edges:Array.from({length:1000},(_,i)=>edge("a","b",`edge-${i}`))});
    const selected=index.edges[index.edges.length-1].key;
    const result=buildIntegratedMap(index,{...options,focusId:"a",selectedEdge:selected});
    expect(result.edges).toHaveLength(MAP_EDGE_BUDGET);expect(result.edges.map(item=>item.key)).toContain(selected);
    expect(index.incident.get("a")).toHaveLength(1000);expect(result.counts.omittedEdges).toBe(100);
    const points=new Map(result.nodes.map(item=>[item.id,item.point]));
    const shapes=result.edges.map(item=>integratedEdgeGeometry(item.edge,item.lane,points.get(item.edge.source)!,points.get(item.edge.target)!));
    expect(new Set(shapes.map(shape=>shape.path)).size).toBe(MAP_EDGE_BUDGET);
    expect(result.bounds.width).toBeLessThan(1600);expect(result.bounds.height).toBeLessThan(1600);
    shapes.forEach(({bounds})=>{
      expect(bounds.x).toBeGreaterThanOrEqual(result.bounds.x);expect(bounds.y).toBeGreaterThanOrEqual(result.bounds.y);
      expect(bounds.x+bounds.width).toBeLessThanOrEqual(result.bounds.x+result.bounds.width);
      expect(bounds.y+bounds.height).toBeLessThanOrEqual(result.bounds.y+result.bounds.height);
    });
  });
  it("draws mirrored self records separately with bounded loops",()=>{
    const index=indexIntegratedGraph({nodes:[node("a")],edges:Array.from({length:100},(_,i)=>edge("a","a",`loop-${i}`))});
    const result=buildIntegratedMap(index,{...options,focusId:"a"}),point=result.nodes[0].point;
    const paths=result.edges.map(item=>integratedEdgeGeometry(item.edge,item.lane,point,point).path);
    expect(new Set(paths).size).toBe(100);expect(result.bounds.width).toBeLessThan(600);expect(result.bounds.height).toBeLessThan(700);
  });
  it("keeps zoomed-out directed tangents toward the recorded target",()=>{
    for(const distance of [20,100,400]) for(const radius of [27,80,300]) for(const lane of [-2,0,2]) {
      const shape=integratedEdgeGeometry(edge("a","b","ab"),lane,{x:0,y:0},{x:distance,y:0},radius);
      const values=shape.path.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
      const [startX,,controlX,,endX]=values;
      expect(startX).toBeLessThan(endX);expect(endX-controlX).toBeGreaterThan(0);
    }
  });
  it("keeps a parallel lane's midpoint separated in screen pixels at zoom-out scales",()=>{
    const record=edge("a","b","ab"),source={x:0,y:0},target={x:400,y:0};
    const initial=integratedEdgeGeometry(record,1,source,target).y;
    for(const scale of [.73,.22,.08]) {
      const shape=integratedEdgeGeometry(record,1,source,target,27,1/scale);
      expect(shape.y*scale).toBeCloseTo(initial,8);
      expect(Math.abs(shape.y*scale)).toBeGreaterThan(18);
    }
  });
  it("returns finite empty-state bounds and an aspect-aware fit",()=>{
    const empty=buildIntegratedMap(indexIntegratedGraph({nodes:[],edges:[]}),{...options,focusId:null});
    expect(empty.nodes).toEqual([]);expect(empty.counts.totalNodes).toBe(0);
    const camera=fitMapCamera({x:-200,y:-100,width:1800,height:900},{width:390,height:400});
    expect(camera.scale).toBeGreaterThan(0);expect(camera.scale*1800).toBeLessThan(390);
    expect(Object.values(camera).every(Number.isFinite)).toBe(true);
  });
});
