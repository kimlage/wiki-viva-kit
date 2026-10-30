// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { restoreSurfaceFocus } from "./restoreSurfaceFocus";

afterEach(() => { document.body.replaceChildren(); });
function controls() {
  const opener=document.createElement("button");
  const input=document.createElement("input");
  document.body.append(opener,input);
  return {opener,input};
}
describe("dismissed surface focus",()=>{
  it("restores the invoker when focus was abandoned",()=>{
    const {opener,input}=controls();restoreSurfaceFocus(opener,input);
    expect(document.activeElement).toBe(opener);
  });
  it("does not steal focus between selecting the next query and inserting its text",()=>{
    const {opener,input}=controls();
    const deferredRestore=()=>restoreSurfaceFocus(opener,input);
    input.focus();input.select();deferredRestore();
    // Browser input insertion follows the focused control, not the locator
    // that selected it before this deferred animation-frame callback ran.
    const target=document.activeElement;
    if(target instanceof HTMLInputElement)target.value="Next evidence page";
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Next evidence page");
  });
  it("preserves a newer keyboard focus outside the dismissed surface",()=>{
    const {opener,input}=controls();const next=document.createElement("button");
    document.body.append(next);next.focus();restoreSurfaceFocus(opener,input);
    expect(document.activeElement).toBe(next);
  });
  it("can restore focus still held by an inert closing surface",()=>{
    const {opener,input}=controls();const closing=document.createElement("div");
    const close=document.createElement("button");closing.append(close);document.body.append(closing);
    close.focus();closing.setAttribute("inert","");restoreSurfaceFocus(opener,input);
    expect(document.activeElement).toBe(opener);
  });
  it("uses the fallback when the original invoker was removed",()=>{
    const {opener,input}=controls();opener.remove();restoreSurfaceFocus(opener,input);
    expect(document.activeElement).toBe(input);
  });
});
