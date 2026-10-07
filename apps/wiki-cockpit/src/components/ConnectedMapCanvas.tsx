import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { BookOpen, Database, Home, Layers, ListChecks, Maximize2, Minus, Plus } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import { fitMapCamera, integratedEdgeGeometry } from "../scene/integratedMap";
import type { IntegratedMap, MapPerspective, MapPoint } from "../scene/integratedMap";
import type { GraphNode } from "../types";

type Camera={x:number;y:number;scale:number};
type Encoding={color:string;label:string;ring:string;symbol:string};

function useMotionPreference(enabled:boolean) {
  const [reduced,setReduced]=useState(()=>window.matchMedia?.("(prefers-reduced-motion: reduce)").matches??false);
  const [visible,setVisible]=useState(()=>document.visibilityState!=="hidden");
  useEffect(()=>{
    const media=window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const update=()=>setReduced(media?.matches??false);
    const visibility=()=>setVisible(document.visibilityState!=="hidden");
    media?.addEventListener("change",update);document.addEventListener("visibilitychange",visibility);
    return()=>{media?.removeEventListener("change",update);document.removeEventListener("visibilitychange",visibility);};
  },[]);
  return {reduced,active:enabled&&!reduced&&visible};
}

function useMovingPoints(target:Map<string,MapPoint>,active:boolean) {
  const [points,setPoints]=useState(target);
  const [moving,setMoving]=useState(false);
  const current=useRef(points);
  useEffect(()=>{
    const from=current.current;
    if (!active || [...target].every(([id,p])=>from.get(id)?.x===p.x&&from.get(id)?.y===p.y)) {
      current.current=target;setPoints(target);setMoving(false);return;
    }
    let frame=0;
    const start=performance.now();setMoving(true);
    const tick=(now:number)=>{
      const progress=Math.min(1,(now-start)/420),ease=1-(1-progress)**3;
      const next=new Map([...target].map(([id,to])=>{
        const old=from.get(id)||to;
        return [id,{x:old.x+(to.x-old.x)*ease,y:old.y+(to.y-old.y)*ease}];
      }));
      current.current=next;setPoints(next);
      if(progress<1)frame=window.requestAnimationFrame(tick);else setMoving(false);
    };
    frame=window.requestAnimationFrame(tick);
    return()=>window.cancelAnimationFrame(frame);
  },[target,active]);
  return {points,moving};
}

const clip=(title:string,n:number)=>title.length>n?`${title.slice(0,n-1)}…`:title;

export function ConnectedMapCanvas({model,perspective,focusId,selectedId,selectedEdge,relation,motion,encodingFor,relationLabel,onSelect,onEdge}: {
  model:IntegratedMap;perspective:MapPerspective;focusId:string|null;selectedId:string|null;
  selectedEdge:string;relation:string;motion:boolean;encodingFor:(node:GraphNode)=>Encoding;
  relationLabel:(type:string)=>string;onSelect:(id:string)=>void;onEdge:(key:string)=>void;
}) {
  const container=useRef<HTMLDivElement>(null);
  const [size,setSize]=useState({width:1000,height:650});
  const [camera,setCamera]=useState<Camera>({x:0,y:0,scale:.5});
  const cameraRef=useRef(camera),cameraFrame=useRef(0);
  const moveCameraRef=useRef<(to:Camera)=>void>(()=>{});
  const [hovered,setHovered]=useState<string|null>(null);
  const [hoveredEdge,setHoveredEdge]=useState<string|null>(null);
  const [keyboardId,setKeyboardId]=useState<string|null>(null);
  const buttons=useRef(new Map<string,HTMLButtonElement>());
  const pointer=useRef<{id:number;x:number;y:number;camera:Camera}|null>(null);
  const preference=useMotionPreference(motion);
  const targets=useMemo(()=>new Map(model.nodes.map(node=>[node.id,node.point])),[model.nodes]);
  const titles=useMemo(()=>new Map(model.nodes.map(node=>[node.id,node.node.title])),[model.nodes]);
  const {points,moving}=useMovingPoints(targets,preference.active);
  const markerId=`map-arrow-${useId().replaceAll(":","")}`;
  const setView=useCallback((next:Camera)=>{cameraRef.current=next;setCamera(next);},[]);
  const stopCamera=useCallback(()=>window.cancelAnimationFrame(cameraFrame.current),[]);
  const moveCamera=useCallback((to:Camera)=>{
    stopCamera();
    if(!preference.active){setView(to);return;}
    const from=cameraRef.current,start=performance.now();
    const tick=(now:number)=>{
      const progress=Math.min(1,(now-start)/320),ease=1-(1-progress)**3;
      setView({x:from.x+(to.x-from.x)*ease,y:from.y+(to.y-from.y)*ease,scale:from.scale+(to.scale-from.scale)*ease});
      if(progress<1)cameraFrame.current=window.requestAnimationFrame(tick);
    };
    cameraFrame.current=window.requestAnimationFrame(tick);
  },[preference.active,setView,stopCamera]);
  moveCameraRef.current=moveCamera;
  useEffect(()=>{if(!preference.active)stopCamera();},[preference.active,stopCamera]);
  useEffect(()=>()=>stopCamera(),[stopCamera]);
  useEffect(()=>{
    const element=container.current;if(!element)return;
    const observer=new ResizeObserver(entries=>{const box=entries[0].contentRect;setSize({width:box.width,height:box.height});});
    observer.observe(element);return()=>observer.disconnect();
  },[]);
  const boundsKey=JSON.stringify(model.bounds);
  useEffect(()=>{moveCameraRef.current(fitMapCamera(model.bounds,size));},[boundsKey,size.width,size.height]);
  const zoomAt=useCallback((factor:number,x=size.width/2,y=size.height/2)=>{
    stopCamera();const view=cameraRef.current;
    const scale=Math.max(.08,Math.min(3.5,view.scale*factor)),ratio=scale/view.scale;
    setView({scale,x:x-(x-view.x)*ratio,y:y-(y-view.y)*ratio});
  },[setView,stopCamera,size.width,size.height]);
  useEffect(()=>{
    const element=container.current;if(!element)return;
    const wheel=(event:WheelEvent)=>{
      if(event.ctrlKey||event.metaKey)return;
      event.preventDefault();const rect=element.getBoundingClientRect();
      zoomAt(Math.exp(-Math.max(-100,Math.min(100,event.deltaY))*.003),event.clientX-rect.left,event.clientY-rect.top);
    };
    element.addEventListener("wheel",wheel,{passive:false});return()=>element.removeEventListener("wheel",wheel);
  },[zoomAt]);
  const reveal=(id:string)=>{
    const point=points.get(id);if(!point)return;
    const screen={x:point.x*cameraRef.current.scale+cameraRef.current.x,y:point.y*cameraRef.current.scale+cameraRef.current.y};
    if(screen.x<60||screen.x>size.width-60||screen.y<60||screen.y>size.height-60)moveCamera({...cameraRef.current,x:size.width/2-point.x*cameraRef.current.scale,y:size.height/2-point.y*cameraRef.current.scale});
  };
  const highlighted=hovered||selectedId;
  const adjacent=new Set<string>(highlighted?[highlighted]:[]);
  model.edges.forEach(({edge})=>{if(edge.source===highlighted)adjacent.add(edge.target);if(edge.target===highlighted)adjacent.add(edge.source);});
  const flowing=new Set(model.edges.filter(({edge,key})=>edge.direction==="directed"&&(selectedEdge?key===selectedEdge:edge.source===selectedId||edge.target===selectedId)).slice(0,8).map(edge=>edge.key));
  const focusNodeId=keyboardId&&points.has(keyboardId)?keyboardId:selectedId&&points.has(selectedId)?selectedId:focusId&&points.has(focusId)?focusId:model.nodes[0]?.id;
  const navigateNode=(id:string,key:string)=>{
    const origin=points.get(id)!;
    const direction=key==="ArrowRight"?{x:1,y:0}:key==="ArrowLeft"?{x:-1,y:0}:key==="ArrowDown"?{x:0,y:1}:{x:0,y:-1};
    const next=model.nodes.filter(node=>node.id!==id).map(node=>{
      const point=points.get(node.id)!,dx=point.x-origin.x,dy=point.y-origin.y;
      const forward=dx*direction.x+dy*direction.y;
      return {id:node.id,forward,score:Math.hypot(dx,dy)+Math.abs(dx*direction.y-dy*direction.x)*2};
    }).filter(node=>node.forward>1).sort((a,b)=>a.score-b.score||a.id.localeCompare(b.id))[0];
    if(next){setKeyboardId(next.id);buttons.current.get(next.id)?.focus({preventScroll:true});reveal(next.id);}
  };
  const labelSize=12/camera.scale;
  const groupLabels=model.groups.length>1?model.groups.map(group=>({...group,label:
    perspective==="network"||perspective==="areas"?(group.key?contextLabel(group.key):t("map.unknownContext")):t(`map.group.${group.key}`)})):[];
  // Place a bounded set of readable labels in screen space. Every page keeps
  // its full accessible name, search result and inspector even when its label
  // cannot fit. Zoom/selection progressively reveals the remaining titles.
  const labelPlacements=new Map<string,{x:number;y:number;anchor:"middle"|"start"|"end";text:string}>();
  const occupied:{x:number;y:number;width:number;height:number}[]=[];
  const groupPlacements=new Map<string,MapPoint>();
  for(const group of [...groupLabels].sort((a,b)=>b.count-a.count)) {
    const width=(clip(group.label,26).length+String(group.count).length+1)*7;
    const origin={x:group.x*camera.scale+camera.x,y:group.y*camera.scale+camera.y};
    if(origin.x<-80||origin.x>size.width+80||origin.y<-80||origin.y>size.height+80)continue;
    let placed=false;
    const offsets=[0,...Array.from({length:Math.ceil(size.height/24)},(_,i)=>[-24*(i+1),24*(i+1)]).flat()];
    for(const dy of offsets) {
      for(const dx of [0,-50,50,-100,100]) {
        const x=Math.max(width/2+8,Math.min(size.width-width/2-8,origin.x+dx)),y=origin.y+dy;
        const rect={x:x-width/2,y:y-13,width,height:18};
        if(rect.y<8||rect.y+18>size.height-52)continue;
        if(occupied.some(box=>rect.x<box.x+box.width+6&&rect.x+rect.width+6>box.x&&rect.y<box.y+box.height+3&&rect.y+rect.height+3>box.y))continue;
        if(model.nodes.some(item=>{
          const point=points.get(item.id)||item.point,nx=point.x*camera.scale+camera.x,ny=point.y*camera.scale+camera.y;
          return nx+18>rect.x&&nx-18<rect.x+width&&ny+18>rect.y&&ny-18<rect.y+18;
        }))continue;
        occupied.push(rect);groupPlacements.set(group.key,{x:(x-camera.x)/camera.scale,y:(y-camera.y)/camera.scale});placed=true;break;
      }
      if(placed)break;
    }
  }
  const labelCandidates=[...model.nodes].filter(item=>item.id===selectedId||item.id===hovered||model.nodes.length<=14||camera.scale>1.1||item.labelPriority)
    .sort((a,b)=>Number(b.id===hovered)-Number(a.id===hovered)||Number(b.id===selectedId)-Number(a.id===selectedId)||Number(b.node.page_type==="context_hub")-Number(a.node.page_type==="context_hub")||a.id.localeCompare(b.id));
  for(const item of labelCandidates) {
    const point=points.get(item.id)||item.point;
    const x=point.x*camera.scale+camera.x,y=point.y*camera.scale+camera.y;
    const text=clip(item.node.title,item.id===selectedId||item.id===hovered?44:26),width=text.length*6.7;
    for(const placement of [{x,y:y+28,anchor:"middle" as const},{x,y:y-23,anchor:"middle" as const},{x:x+23,y:y+4,anchor:"start" as const},{x:x-23,y:y+4,anchor:"end" as const}]) {
      const rect={x:placement.x-(placement.anchor==="middle"?width/2:placement.anchor==="end"?width:0),y:placement.y-12,width,height:17};
      if(rect.x<8||rect.x+width>size.width-8||rect.y<8||rect.y+17>size.height-40)continue;
      if(occupied.some(box=>rect.x<box.x+box.width+6&&rect.x+rect.width+6>box.x&&rect.y<box.y+box.height+3&&rect.y+rect.height+3>box.y))continue;
      if(model.nodes.some(other=>{
        if(other.id===item.id)return false;const otherPoint=points.get(other.id)||other.point;
        const nx=otherPoint.x*camera.scale+camera.x,ny=otherPoint.y*camera.scale+camera.y;
        return nx+16>rect.x&&nx-16<rect.x+width&&ny+16>rect.y&&ny-16<rect.y+17;
      }))continue;
      occupied.push(rect);labelPlacements.set(item.id,{x:(placement.x-camera.x)/camera.scale,y:(placement.y-camera.y)/camera.scale,anchor:placement.anchor,text});break;
    }
  }
  return <div className="focusMapCanvas" ref={container} data-testid="map-canvas" data-layout-motion={moving?"moving":"settled"} data-motion={preference.active?"on":"off"} data-camera-scale={camera.scale.toFixed(3)}>
    <svg data-testid="focus-svg" role="group" aria-label={t("map.title")} width="100%" height="100%" viewBox={`0 0 ${size.width} ${size.height}`}
      onPointerDown={event=>{
        if((event.target as Element).closest("button,[role=button]"))return;
        stopCamera();pointer.current={id:event.pointerId,x:event.clientX,y:event.clientY,camera:cameraRef.current};event.currentTarget.setPointerCapture(event.pointerId);
      }} onPointerMove={event=>{
        const drag=pointer.current;if(!drag||drag.id!==event.pointerId)return;
        setView({...drag.camera,x:drag.camera.x+event.clientX-drag.x,y:drag.camera.y+event.clientY-drag.y});
      }} onPointerUp={()=>{pointer.current=null;}} onPointerCancel={()=>{pointer.current=null;}}>
      <defs><marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs>
      <g transform={`translate(${camera.x} ${camera.y}) scale(${camera.scale})`}>
        {model.edges.map(item=>{
          const source=points.get(item.edge.source),target=points.get(item.edge.target);if(!source||!target)return null;
          const shape=integratedEdgeGeometry(item.edge,item.lane,source,target,14/camera.scale+8);
          const selected=item.key===selectedEdge,hot=selected||item.key===hoveredEdge;
          const incident=item.edge.source===highlighted||item.edge.target===highlighted;
          const dim=relation?item.edge.type!==relation:highlighted&&!incident&&!hot;
          return <g key={item.key} className={`focusMapEdge${selected?" selected":""}${hot||incident?" highlighted":""}${dim?" muted":""}`} data-navigation={item.edge.type==="moc_parent"?"true":"false"}>
            <path className="focusMapEdgeLine" d={shape.path} markerEnd={item.edge.direction==="directed"?`url(#${markerId})`:undefined} />
            {preference.active&&flowing.has(item.key)&&!dim&&<path className="focusMapFlow" data-direction="directed" d={shape.path} pathLength={100} strokeDasharray="3 97" aria-hidden="true" />}
            <path className="focusMapEdgeHit" d={shape.path} role="button" tabIndex={-1} aria-pressed={selected}
              aria-label={`${relationLabel(item.edge.type)}: ${titles.get(item.edge.source)} ${item.edge.direction==="directed"?"→":"—"} ${titles.get(item.edge.target)}`}
              data-edge-key={item.key} data-edge-id={item.edge.id||""} onClick={()=>onEdge(item.key)}
              onMouseEnter={()=>setHoveredEdge(item.key)} onMouseLeave={()=>setHoveredEdge(null)}
              onFocus={()=>setHoveredEdge(item.key)} onBlur={()=>setHoveredEdge(null)}
              onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();onEdge(item.key);}}} />
            {hot&&<text className="focusMapEdgeLabel" x={shape.x} y={shape.y-8} fontSize={labelSize} aria-hidden="true">{relationLabel(item.edge.type)}</text>}
          </g>;
        })}
        {model.nodes.map(item=>{
          const point=points.get(item.id)||item.point,encoding=encodingFor(item.node);
          const selected=item.id===selectedId,hot=item.id===hovered;
          const muted=Boolean(highlighted&&!adjacent.has(item.id));
          const label=labelPlacements.get(item.id);
          const hit=44/camera.scale,dot=28/camera.scale;
          const Icon=item.node.page_type==="source"?Database:item.node.page_type==="action"?ListChecks:item.node.page_type==="root_entity"?Home:item.node.page_type==="context_hub"?Layers:BookOpen;
          return <g key={item.id} className={`focusMapNodeGroup${muted?" muted":""}${selected?" selected":""}`} data-node-id={item.id}>
            <foreignObject x={point.x-hit/2} y={point.y-hit/2} width={hit} height={hit}>
              <button type="button" className={`focusMapNode${selected?" selected":""}${item.id===focusId?" focal":""}`} ref={element=>{if(element)buttons.current.set(item.id,element);else buttons.current.delete(item.id);}}
                style={{"--focus-map-data-color":encoding.color,"--map-dot":`${dot}px`,"--map-icon":`${14/camera.scale}px`} as CSSProperties}
                data-ring={encoding.ring} data-encoding-label={`${encoding.symbol} ${encoding.label}`.trim()} data-testid={`focus-node-${item.id}`} aria-pressed={selected}
                aria-label={`${item.node.title} · ${encoding.label}`} tabIndex={focusNodeId===item.id?0:-1}
                onClick={()=>onSelect(item.id)} onMouseEnter={()=>setHovered(item.id)} onMouseLeave={()=>setHovered(null)} onFocus={()=>{setHovered(item.id);setKeyboardId(item.id);}} onBlur={()=>setHovered(null)}
                onKeyDown={event=>{
                  if(event.key.startsWith("Arrow")){event.preventDefault();navigateNode(item.id,event.key);}
                  if(event.key==="+"||event.key==="="){event.preventDefault();zoomAt(1.2);}
                  if(event.key==="-"){event.preventDefault();zoomAt(1/1.2);}
                  if(event.key==="Home"){event.preventDefault();moveCamera(fitMapCamera(model.bounds,size));}
                }}><span className="focusMapDot"><Icon aria-hidden="true" /></span></button>
            </foreignObject>
            {label&&<text className="focusMapNodeLabel" x={label.x} y={label.y} textAnchor={label.anchor} fontSize={labelSize} aria-hidden="true">{label.text}</text>}
          </g>;
        })}
        {groupLabels.map(group=>{const point=groupPlacements.get(group.key);return point&&<text key={group.key} className="focusMapCluster" x={point.x} y={point.y} textAnchor="middle" fontSize={labelSize}>
          <title>{group.label} · {group.count}</title>{clip(group.label,26)} <tspan className="focusMapClusterCount">{group.count}</tspan>
        </text>;})}
      </g>
    </svg>
    <div className="focusMapCanvasTools"><span>{t("map.graphHint")}</span><div>
      <button type="button" aria-label={t("map.zoomOut")} onClick={()=>zoomAt(1/1.25)}><Minus size={17}/></button>
      <button type="button" aria-label={t("map.zoomIn")} onClick={()=>zoomAt(1.25)}><Plus size={17}/></button>
      <button type="button" aria-label={t("map.fit")} onClick={()=>moveCamera(fitMapCamera(model.bounds,size))}><Maximize2 size={17}/></button>
    </div></div>
    <span className="focusMapSrOnly">{t("map.keyboardHint")}</span>
  </div>;
}
