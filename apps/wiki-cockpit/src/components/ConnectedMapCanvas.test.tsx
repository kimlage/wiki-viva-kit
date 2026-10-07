// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../data/i18n";
import { buildIntegratedMap, indexIntegratedGraph } from "../scene/integratedMap";
import type { GraphNode } from "../types";
import { ConnectedMapCanvas } from "./ConnectedMapCanvas";

const node=(id:string):GraphNode=>({id,path:`memories/${id}.md`,title:id,page_type:"claim",context:"example",freshness_state:"unknown",approved_state:"approved",risk_flags:[],metrics:{inbound_links:0,outbound_links:0,source_ref_count:0}});
const model=buildIntegratedMap(indexIntegratedGraph({nodes:[node("a"),node("b")],edges:[{id:"ab",source:"a",target:"b",type:"source_ref",direction:"directed",weight:1,status:"valid"}]}),{scope:"all",focusId:"a",perspective:"network"});
const props={model,perspective:"network" as const,focusId:"a",selectedId:null,selectedEdge:"",relation:"",motion:true,encodingFor:()=>({color:"var(--wiki-accent)",label:"example",ring:"solid",symbol:""}),relationLabel:()=>"uses as source",onSelect:vi.fn(),onEdge:vi.fn(),onClear:vi.fn()};
let now=0,nextFrame=0;
let frames:Map<number,FrameRequestCallback>;
let media:MediaQueryList;
let mediaListeners:Set<()=>void>;
const advance=(time:number)=>act(()=>{now=time;const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback(time));});
const transform=()=>screen.getByTestId("focus-svg").querySelector(":scope > g")!.getAttribute("transform");
const beginFit=()=>{
  const initial=transform();
  fireEvent.click(screen.getByRole("button",{name:t("map.zoomOut")}));
  expect(transform()).not.toBe(initial);
  fireEvent.click(screen.getByRole("button",{name:t("map.fit")}));
  advance(now+80);
  expect(transform()).not.toBe(initial);
  expect(screen.getByTestId("map-canvas").dataset.cameraMotion).toBe("moving");
  return initial;
};

beforeEach(()=>{
  configureLanguage("en");now=0;nextFrame=0;frames=new Map();mediaListeners=new Set();
  Object.defineProperty(document,"visibilityState",{configurable:true,value:"visible"});
  media={matches:false,addEventListener:(_type:string,listener:()=>void)=>mediaListeners.add(listener),removeEventListener:(_type:string,listener:()=>void)=>mediaListeners.delete(listener)} as unknown as MediaQueryList;
  vi.stubGlobal("matchMedia",()=>media);
  vi.stubGlobal("ResizeObserver",class {observe(){}disconnect(){}});
  vi.spyOn(performance,"now").mockImplementation(()=>now);
  vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++nextFrame,callback);return nextFrame;});
  vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id);});
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.clearAllMocks();configureLanguage("en");});

describe("pending connected-map camera",()=>{
  for(const reason of ["pause","reduced","hidden"] as const)it(`finishes the pending fit when ${reason} interrupts an intermediate frame`,()=>{
    const view=render(<ConnectedMapCanvas {...props}/>);
    advance(400);const fitted=beginFit();
    act(()=>{
      if(reason==="pause")view.rerender(<ConnectedMapCanvas {...props} motion={false}/>);
      else if(reason==="reduced"){Object.defineProperty(media,"matches",{value:true});mediaListeners.forEach(listener=>listener());}
      else{Object.defineProperty(document,"visibilityState",{configurable:true,value:"hidden"});document.dispatchEvent(new Event("visibilitychange"));}
    });
    expect(transform()).toBe(fitted);
    expect(screen.getByTestId("map-canvas").dataset.cameraMotion).toBe("settled");
    advance(1000);expect(transform()).toBe(fitted);
    act(()=>{
      if(reason==="pause")view.rerender(<ConnectedMapCanvas {...props} motion={true}/>);
      else if(reason==="reduced"){Object.defineProperty(media,"matches",{value:false});mediaListeners.forEach(listener=>listener());}
      else{Object.defineProperty(document,"visibilityState",{configurable:true,value:"visible"});document.dispatchEvent(new Event("visibilitychange"));}
    });
    advance(1400);expect(transform()).toBe(fitted);
  });

  for(const action of ["zoom","pan"] as const)it(`does not restore an obsolete fit after manual ${action}`,()=>{
    const view=render(<ConnectedMapCanvas {...props}/>);
    advance(400);beginFit();
    if(action==="zoom")fireEvent.click(screen.getByRole("button",{name:t("map.zoomIn")}));
    else {
      const svg=screen.getByTestId("focus-svg") as unknown as SVGSVGElement;
      svg.setPointerCapture=()=>{};
      fireEvent.pointerDown(svg,{pointerId:1,clientX:20,clientY:20});
      fireEvent.pointerMove(svg,{pointerId:1,clientX:65,clientY:65});
      fireEvent.pointerUp(svg,{pointerId:1,clientX:65,clientY:65});
      expect(props.onClear).not.toHaveBeenCalled();
    }
    const manual=transform();
    view.rerender(<ConnectedMapCanvas {...props} motion={false}/>);
    expect(transform()).toBe(manual);
    advance(1000);expect(transform()).toBe(manual);
  });
});
