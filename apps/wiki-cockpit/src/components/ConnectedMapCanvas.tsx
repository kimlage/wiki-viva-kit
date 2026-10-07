import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { BookOpen, Database, Home, Layers, ListChecks, Maximize2, Minus, Plus, X } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel, pageTypeLabel } from "../data/presentation";
import { mapRelationStyle } from "../data/mapRelations";
import { fitMapCamera, integratedEdgeGeometry } from "../scene/integratedMap";
import type { IntegratedMap, MapPerspective, MapPoint } from "../scene/integratedMap";
import type { GraphNode } from "../types";

type Camera={x:number;y:number;scale:number};
type Encoding={color:string;label:string;ring:string;symbol:string};
type MapTarget={kind:"node";id:string}|{kind:"edge";id:string};
type PreviewBridge={origin:MapPoint;rect:{left:number;right:number;top:number;bottom:number};expires:number};

function headsTowardPreview(point:MapPoint,bridge:PreviewBridge) {
  const {origin,rect}=bridge;
  const left=rect.left-8,right=rect.right+8,top=rect.top-8,bottom=rect.bottom+8;
  if(point.x>=left&&point.x<=right&&point.y>=top&&point.y<=bottom)return true;
  const corners=origin.y<top?[{x:left,y:top},{x:right,y:top}]:origin.y>bottom?[{x:left,y:bottom},{x:right,y:bottom}]:origin.x<left?[{x:left,y:top},{x:left,y:bottom}]:origin.x>right?[{x:right,y:top},{x:right,y:bottom}]:null;
  if(!corners)return false;
  const side=(a:MapPoint,b:MapPoint)=>(b.x-a.x)*(point.y-a.y)-(b.y-a.y)*(point.x-a.x);
  const signs=[side(origin,corners[0]),side(corners[0],corners[1]),side(corners[1],origin)];
  return signs.every(value=>value>=-2)||signs.every(value=>value<=2);
}

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

export function ConnectedMapCanvas({model,perspective,focusId,selectedId,selectedEdge,relation,motion,encodingFor,relationLabel,onSelect,onEdge,onClear}: {
  model:IntegratedMap;perspective:MapPerspective;focusId:string|null;selectedId:string|null;
  selectedEdge:string;relation:string;motion:boolean;encodingFor:(node:GraphNode)=>Encoding;
  relationLabel:(type:string)=>string;onSelect:(id:string)=>void;onEdge:(key:string)=>void;onClear:()=>void;
}) {
  const container=useRef<HTMLDivElement>(null);
  const [size,setSize]=useState({width:1000,height:650});
  const [camera,setCamera]=useState<Camera>({x:0,y:0,scale:.5});
  const cameraRef=useRef(camera),cameraFrame=useRef(0),cameraTarget=useRef<Camera|null>(null);
  const moveCameraRef=useRef<(to:Camera)=>void>(()=>{});
  const [pointerTarget,setPointerTarget]=useState<MapTarget|null>(null);
  const [focusTarget,setFocusTarget]=useState<MapTarget|null>(null);
  const hidePreview=useRef(0),tooltip=useRef<HTMLElement>(null);
  const previewBridge=useRef<PreviewBridge|null>(null),lastPointer=useRef<MapPoint>({x:0,y:0});
  const [tooltipHeight,setTooltipHeight]=useState(160);
  const [keyboardId,setKeyboardId]=useState<string|null>(null);
  const [keyboardEdge,setKeyboardEdge]=useState<string|null>(null);
  const buttons=useRef(new Map<string,HTMLButtonElement>());
  const edgeButtons=useRef(new Map<string,SVGPathElement>());
  const pointer=useRef<{id:number;x:number;y:number;camera:Camera;moved:boolean}|null>(null);
  const preference=useMotionPreference(motion);
  const targets=useMemo(()=>new Map(model.nodes.map(node=>[node.id,node.point])),[model.nodes]);
  const titles=useMemo(()=>new Map(model.nodes.map(node=>[node.id,node.node.title])),[model.nodes]);
  const {points,moving}=useMovingPoints(targets,preference.active);
  const markerId=`map-arrow-${useId().replaceAll(":","")}`;
  const previewId=`map-preview-${useId().replaceAll(":","")}`;
  const cancelPreviewHide=()=>window.clearTimeout(hidePreview.current);
  const leavePointer=(event:ReactPointerEvent<Element>)=>{
    lastPointer.current={x:event.clientX,y:event.clientY};
    const rect=tooltip.current?.getBoundingClientRect();
    if(tooltip.current?.contains(event.currentTarget))previewBridge.current=null;
    else if(rect&&(!previewBridge.current||previewBridge.current.expires<=performance.now()))previewBridge.current={origin:lastPointer.current,rect,expires:performance.now()+500};
    cancelPreviewHide();hidePreview.current=window.setTimeout(()=>{
      previewBridge.current=null;
      const hit=document.elementFromPoint(lastPointer.current.x,lastPointer.current.y);
      if(hit&&tooltip.current?.contains(hit))return;
      const edge=hit&&container.current?.contains(hit)?hit.closest("[data-edge-key],[data-edge-owner]"):null;
      const node=hit&&container.current?.contains(hit)?hit.closest<HTMLButtonElement>(".focusMapNode[data-testid]"):null;
      const key=edge?.getAttribute("data-edge-key")||edge?.getAttribute("data-edge-owner");
      setPointerTarget(key?{kind:"edge",id:key}:node?{kind:"node",id:node.dataset.testid!.slice("focus-node-".length)}:null);
    },500);
  };
  const enterPointer=(target:MapTarget,event:ReactPointerEvent<Element>)=>{
    lastPointer.current={x:event.clientX,y:event.clientY};
    const bridge=previewBridge.current;
    if(pointerTarget&&(pointerTarget.kind!==target.kind||pointerTarget.id!==target.id)&&bridge&&bridge.expires>performance.now()&&headsTowardPreview(lastPointer.current,bridge))return;
    previewBridge.current=null;cancelPreviewHide();setPointerTarget(target);
  };
  const focus=(target:MapTarget)=>{previewBridge.current=null;cancelPreviewHide();setPointerTarget(null);setFocusTarget(target);};
  const blur=(next:EventTarget|null)=>{if(!(next instanceof Node)||!tooltip.current?.contains(next))setFocusTarget(null);};
  const clearHighlight=()=>{previewBridge.current=null;cancelPreviewHide();setPointerTarget(null);setFocusTarget(null);onClear();};
  useEffect(()=>()=>window.clearTimeout(hidePreview.current),[]);
  useEffect(()=>{
    const track=(event:PointerEvent)=>{lastPointer.current={x:event.clientX,y:event.clientY};};
    document.addEventListener("pointermove",track);return()=>document.removeEventListener("pointermove",track);
  },[]);
  // Pointer and keyboard exploration are ephemeral. Only the existing route
  // records a clicked/tapped selection, so hover never navigates or reads.
  const previewTarget=pointerTarget||focusTarget;
  const activeTarget=previewTarget||(selectedEdge?{kind:"edge" as const,id:selectedEdge}:selectedId?{kind:"node" as const,id:selectedId}:null);
  const hovered=previewTarget?.kind==="node"?previewTarget.id:null;
  const activeEdge=activeTarget?.kind==="edge"?model.edges.find(item=>item.key===activeTarget.id):null;
  const previewNode=previewTarget?.kind==="node"?model.nodes.find(item=>item.id===previewTarget.id):null;
  const previewEdge=previewTarget?.kind==="edge"?model.edges.find(item=>item.key===previewTarget.id):null;
  useLayoutEffect(()=>{if(tooltip.current)setTooltipHeight(tooltip.current.getBoundingClientRect().height);},[previewNode?.id,previewEdge?.key,size.width]);
  useEffect(()=>{previewBridge.current=null;cancelPreviewHide();setPointerTarget(null);setFocusTarget(null);},[model,perspective]);
  const setView=useCallback((next:Camera)=>{cameraRef.current=next;setCamera(next);},[]);
  const stopCamera=useCallback(()=>{
    window.cancelAnimationFrame(cameraFrame.current);cameraFrame.current=0;cameraTarget.current=null;
  },[]);
  const moveCamera=useCallback((to:Camera)=>{
    stopCamera();
    if(!preference.active){setView(to);return;}
    cameraTarget.current=to;
    const from=cameraRef.current,start=performance.now();
    const tick=(now:number)=>{
      const progress=Math.min(1,(now-start)/320),ease=1-(1-progress)**3;
      setView({x:from.x+(to.x-from.x)*ease,y:from.y+(to.y-from.y)*ease,scale:from.scale+(to.scale-from.scale)*ease});
      if(progress<1)cameraFrame.current=window.requestAnimationFrame(tick);
      else {cameraFrame.current=0;cameraTarget.current=null;}
    };
    cameraFrame.current=window.requestAnimationFrame(tick);
  },[preference.active,setView,stopCamera]);
  moveCameraRef.current=moveCamera;
  useEffect(()=>{
    if(!preference.active){const target=cameraTarget.current;stopCamera();if(target)setView(target);}
  },[preference.active,setView,stopCamera]);
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
  const highlighted=activeTarget?.kind==="node"?activeTarget.id:null;
  const adjacent=new Set<string>(highlighted?[highlighted]:[]);
  model.edges.forEach(({edge})=>{if(edge.source===highlighted)adjacent.add(edge.target);if(edge.target===highlighted)adjacent.add(edge.source);});
  if(activeEdge){adjacent.add(activeEdge.edge.source);adjacent.add(activeEdge.edge.target);}
  const flowing=new Set(model.edges.filter(({edge,key})=>edge.direction==="directed"&&(activeEdge?key===activeEdge.key:edge.source===highlighted||edge.target===highlighted)).slice(0,8).map(edge=>edge.key));
  const focusNodeId=keyboardId&&points.has(keyboardId)?keyboardId:selectedId&&points.has(selectedId)?selectedId:focusId&&points.has(focusId)?focusId:model.nodes[0]?.id;
  const focusEdgeKey=[keyboardEdge,selectedEdge].find(key=>key&&model.edges.some(item=>item.key===key))||model.edges[0]?.key;
  const focusEdge=(key:string)=>{
    const item=model.edges.find(edge=>edge.key===key);if(!item)return;
    setKeyboardEdge(key);edgeButtons.current.get(key)?.focus({preventScroll:true});
    reveal(item.edge.source);
  };
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
  const markerStyles=[...new Map(model.edges.map(({edge})=>{const style=mapRelationStyle(edge.type);return [style.key,style];})).values()];
  const laneScale=Math.max(1,1/camera.scale);
  const edgeShapes=useMemo(()=>new Map(model.edges.flatMap(item=>{
    const source=points.get(item.edge.source)||targets.get(item.edge.source),target=points.get(item.edge.target)||targets.get(item.edge.target);
    return source&&target?[[item.key,integratedEdgeGeometry(item.edge,item.lane,source,target,14/camera.scale+8,laneScale)] as const]:[];
  })),[model.edges,points,targets,camera.scale,laneScale]);
  const previewPoint=previewNode?points.get(previewNode.id)||previewNode.point:previewEdge?edgeShapes.get(previewEdge.key):null;
  const previewWidth=Math.min(280,size.width-16);
  const previewAnchor=previewPoint?{x:previewPoint.x*camera.scale+camera.x,y:previewPoint.y*camera.scale+camera.y}:null;
  const previewTop=previewAnchor?Math.max(8,Math.min(size.height-tooltipHeight-52,previewAnchor.y+24+tooltipHeight<size.height-52?previewAnchor.y+24:previewAnchor.y-tooltipHeight-24)):8;
  // A short canvas cannot fit a readable card above/below its trigger. Keep
  // its pointer targets free and put the card at the viewport's bottom instead.
  const compactPreview=size.width<600&&size.height<360;
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
  const inspect=(target:MapTarget)=>{
    // The preview action disappears after inspection. Keep keyboard focus on
    // a persistent map surface before recording the opener or changing panels.
    container.current?.focus({preventScroll:true});
    previewBridge.current=null;cancelPreviewHide();setPointerTarget(null);setFocusTarget(null);
    if(target.kind==="edge")onEdge(target.id);else onSelect(target.id);
  };
  const previewCard=previewAnchor&&(previewNode||previewEdge)&&<section ref={tooltip} id={previewId} data-testid="map-tooltip" data-placement={compactPreview?"viewport":"canvas"} className="focusMapTooltip" role="dialog" aria-modal="false" aria-label={t(previewEdge?"map.edgePreview":"map.nodePreview")}
      style={{width:previewWidth,left:Math.max(8,Math.min(size.width-previewWidth-8,previewAnchor.x-previewWidth/2)),top:previewTop}}
      onPointerEnter={()=>{previewBridge.current=null;cancelPreviewHide();}} onPointerLeave={leavePointer} onFocusCapture={()=>{if(previewTarget)setFocusTarget(previewTarget);}} onBlurCapture={event=>blur(event.relatedTarget)}
      onKeyDown={event=>{if(event.key==="Tab"&&event.shiftKey&&event.target===tooltip.current?.querySelector("button")&&previewTarget){event.preventDefault();if(previewTarget.kind==="edge")edgeButtons.current.get(previewTarget.id)?.focus();else buttons.current.get(previewTarget.id)?.focus();}}}>
      <div className="focusMapSectionHeading"><strong>{previewEdge?relationLabel(previewEdge.edge.type):previewNode!.node.title}</strong><button type="button" aria-label={t("map.clearHighlight")} onClick={()=>{clearHighlight();container.current?.focus({preventScroll:true});}}><X size={15}/></button></div>
      {previewEdge?<><p className="focusMapTooltipEndpoints">{titles.get(previewEdge.edge.source)} <span>{previewEdge.edge.direction==="directed"?"→":"—"}</span> {titles.get(previewEdge.edge.target)}</p>
        <small>{t(previewEdge.edge.direction==="directed"?"map.directed":previewEdge.edge.direction==="undirected"?"map.undirected":"map.noDirection")}</small>
        <button type="button" data-testid="map-tooltip-inspect" onClick={()=>inspect({kind:"edge",id:previewEdge.key})}>{t("map.inspectConnection")}</button></>:<><p>{pageTypeLabel(previewNode!.node.page_type)} · {contextLabel(previewNode!.node.context)}</p><small>{t("map.visibleNeighbors",{n:Math.max(0,adjacent.size-1)})}</small><button type="button" data-testid="map-tooltip-inspect" onClick={()=>inspect({kind:"node",id:previewNode!.id})}>{t("map.inspectPage")}</button></>}
    </section>;
  return <div className="focusMapCanvas" ref={container} tabIndex={-1} aria-label={t("map.graph")} data-testid="map-canvas" data-layout-motion={moving?"moving":"settled"} data-camera-motion={cameraTarget.current?"moving":"settled"} data-motion={preference.active?"on":"off"} data-camera-scale={camera.scale.toFixed(3)}
    data-active-kind={activeTarget?.kind||""} data-active-id={activeTarget?.id||""}
    onKeyDown={event=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();clearHighlight();container.current?.focus({preventScroll:true});}}}>
    <svg data-testid="focus-svg" role="group" aria-label={t("map.title")} width="100%" height="100%" viewBox={`0 0 ${size.width} ${size.height}`}
      onPointerDown={event=>{
        if((event.target as Element).closest("button,[role=button],[data-edge-owner]"))return;
        stopCamera();pointer.current={id:event.pointerId,x:event.clientX,y:event.clientY,camera:cameraRef.current,moved:false};event.currentTarget.setPointerCapture(event.pointerId);
      }} onPointerMove={event=>{
        const drag=pointer.current;if(!drag||drag.id!==event.pointerId)return;
        if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>3)drag.moved=true;
        setView({...drag.camera,x:drag.camera.x+event.clientX-drag.x,y:drag.camera.y+event.clientY-drag.y});
      }} onPointerUp={()=>{const drag=pointer.current;pointer.current=null;if(drag&&!drag.moved)clearHighlight();}} onPointerCancel={()=>{pointer.current=null;}}>
      <defs>{markerStyles.map(style=><marker key={style.key} id={`${markerId}-${style.key}`} markerWidth={8/camera.scale} markerHeight={8/camera.scale} viewBox="0 0 8 8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse" style={{"--map-relation-color":style.color} as CSSProperties}><path d="M 0 0 L 8 4 L 0 8 z" /></marker>)}</defs>
      <g transform={`translate(${camera.x} ${camera.y}) scale(${camera.scale})`}>
        {model.edges.map(item=>{
          const shape=edgeShapes.get(item.key);if(!shape)return null;
          const style=mapRelationStyle(item.edge.type);
          const selected=item.key===selectedEdge,hot=item.key===activeEdge?.key;
          const incident=item.edge.source===highlighted||item.edge.target===highlighted;
          const dim=!hot&&Boolean((relation&&item.edge.type!==relation)||(activeTarget&&!incident));
          return <g key={item.key} className={`focusMapEdge${selected?" selected":""}${hot||incident?" highlighted":""}${dim?" muted":""}`} data-relation-type={item.edge.type} data-navigation={item.edge.type==="moc_parent"?"true":"false"} style={{"--map-relation-color":style.color} as CSSProperties}>
            <path className="focusMapEdgeLine" d={shape.path} vectorEffect="non-scaling-stroke" strokeDasharray={style.dash} markerEnd={item.edge.direction==="directed"?`url(#${markerId}-${style.key})`:undefined} />
            {preference.active&&flowing.has(item.key)&&!dim&&<path className="focusMapFlow" data-direction="directed" d={shape.path} pathLength={100} strokeDasharray="3 97" aria-hidden="true" />}
            <path className="focusMapEdgeHit" d={shape.path} vectorEffect="non-scaling-stroke" role="button" tabIndex={focusEdgeKey===item.key?0:-1} aria-pressed={selected}
              ref={element=>{if(element)edgeButtons.current.set(item.key,element);else edgeButtons.current.delete(item.key);}}
              aria-label={`${relationLabel(item.edge.type)}: ${titles.get(item.edge.source)} ${item.edge.direction==="directed"?"→":"—"} ${titles.get(item.edge.target)}`}
              aria-describedby={previewEdge?.key===item.key?previewId:undefined} aria-controls={previewEdge?.key===item.key?previewId:undefined} aria-haspopup="dialog"
              data-edge-key={item.key} data-edge-id={item.edge.id||""} onClick={()=>inspect({kind:"edge",id:item.key})}
              onPointerEnter={event=>{if(event.pointerType!=="touch")enterPointer({kind:"edge",id:item.key},event);}} onPointerLeave={leavePointer}
              onFocus={()=>{focus({kind:"edge",id:item.key});setKeyboardEdge(item.key);}} onBlur={event=>blur(event.relatedTarget)}
              onKeyDown={event=>{
                if(event.key==="Enter"||event.key===" "){event.preventDefault();inspect({kind:"edge",id:item.key});}
                if(event.key.startsWith("Arrow")){event.preventDefault();const index=model.edges.findIndex(edge=>edge.key===item.key),step=event.key==="ArrowLeft"||event.key==="ArrowUp"?-1:1;focusEdge(model.edges[(index+step+model.edges.length)%model.edges.length].key);}
                if(event.key==="Home"){event.preventDefault();moveCamera(fitMapCamera(model.bounds,size));}
                if(event.key==="Tab"&&!event.shiftKey&&previewEdge?.key===item.key&&tooltip.current){event.preventDefault();tooltip.current.querySelector("button")?.focus();}
              }} />
            {hot&&<text className="focusMapEdgeLabel" x={shape.x} y={shape.y-8} fontSize={labelSize} aria-hidden="true">{relationLabel(item.edge.type)}</text>}
          </g>;
        })}
        {/* Visible centers win over every broad transparent band. These pointer
            surfaces share the existing record's single keyboard target. */}
        <g aria-hidden="true">{model.edges.map(item=>{
          const shape=edgeShapes.get(item.key);return shape&&<path key={item.key} className="focusMapEdgeVisibleHit" d={shape.path} vectorEffect="non-scaling-stroke" data-edge-owner={item.key} data-edge-id={item.edge.id||""}
            onClick={()=>inspect({kind:"edge",id:item.key})}
            onPointerEnter={event=>{if(event.pointerType!=="touch")enterPointer({kind:"edge",id:item.key},event);}} onPointerLeave={leavePointer}/>;
        })}</g>
        {model.nodes.map(item=>{
          const point=points.get(item.id)||item.point,encoding=encodingFor(item.node);
          const selected=item.id===selectedId;
          const muted=Boolean(activeTarget&&!adjacent.has(item.id));
          const label=labelPlacements.get(item.id);
          const hit=44/camera.scale,dot=28/camera.scale;
          const Icon=item.node.page_type==="source"?Database:item.node.page_type==="action"?ListChecks:item.node.page_type==="root_entity"?Home:item.node.page_type==="context_hub"?Layers:BookOpen;
          return <g key={item.id} className={`focusMapNodeGroup${muted?" muted":""}${selected?" selected":""}${activeTarget&&adjacent.has(item.id)?" highlighted":""}`} data-node-id={item.id}>
            <foreignObject x={point.x-hit/2} y={point.y-hit/2} width={hit} height={hit}>
              <button type="button" className={`focusMapNode${selected?" selected":""}${item.id===focusId?" focal":""}`} ref={element=>{if(element)buttons.current.set(item.id,element);else buttons.current.delete(item.id);}}
                style={{"--focus-map-data-color":encoding.color,"--map-dot":`${dot}px`,"--map-icon":`${14/camera.scale}px`} as CSSProperties}
                data-ring={encoding.ring} data-encoding-label={`${encoding.symbol} ${encoding.label}`.trim()} data-testid={`focus-node-${item.id}`} aria-pressed={selected}
                aria-label={`${item.node.title} · ${encoding.label}`} tabIndex={focusNodeId===item.id?0:-1}
                aria-describedby={previewNode?.id===item.id?previewId:undefined} aria-controls={previewNode?.id===item.id?previewId:undefined} aria-haspopup="dialog"
                onClick={()=>inspect({kind:"node",id:item.id})} onPointerEnter={event=>{if(event.pointerType!=="touch")enterPointer({kind:"node",id:item.id},event);}} onPointerLeave={leavePointer} onFocus={()=>{focus({kind:"node",id:item.id});setKeyboardId(item.id);}} onBlur={event=>blur(event.relatedTarget)}
                onKeyDown={event=>{
                  if(event.key.startsWith("Arrow")){event.preventDefault();navigateNode(item.id,event.key);}
                  if(event.key==="+"||event.key==="="){event.preventDefault();zoomAt(1.2);}
                  if(event.key==="-"){event.preventDefault();zoomAt(1/1.2);}
                  if(event.key==="Home"){event.preventDefault();moveCamera(fitMapCamera(model.bounds,size));}
                  if(event.key.toLowerCase()==="e"&&!event.altKey&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const edge=model.edges.find(({edge})=>edge.source===item.id||edge.target===item.id);if(edge)focusEdge(edge.key);}
                  if(event.key==="Tab"&&!event.shiftKey&&previewNode?.id===item.id&&tooltip.current){event.preventDefault();tooltip.current.querySelector("button")?.focus();}
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
    {previewCard&&(compactPreview?createPortal(previewCard,container.current?.closest(".focusMap")||document.body):previewCard)}
    <div className="focusMapCanvasTools"><span>{t("map.graphHint")}</span><div>
      <button type="button" aria-label={t("map.zoomOut")} onClick={()=>zoomAt(1/1.25)}><Minus size={17}/></button>
      <button type="button" aria-label={t("map.zoomIn")} onClick={()=>zoomAt(1.25)}><Plus size={17}/></button>
      <button type="button" aria-label={t("map.fit")} onClick={()=>moveCamera(fitMapCamera(model.bounds,size))}><Maximize2 size={17}/></button>
    </div></div>
    <span className="focusMapSrOnly">{t("map.keyboardHint")}</span>
  </div>;
}
