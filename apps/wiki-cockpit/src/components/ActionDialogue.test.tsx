// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ActionDialogue } from "./ActionDialogue";
import type { DialogueEvent } from "../data/actionBoard";
import relationshipCases from "../data/fixtures/action-dialogue-relationships.json";
afterEach(cleanup);
it.each(relationshipCases.filter(item => !item.valid))("keeps invalid reply relationships inert: $name", ({events}) => {
  const send = vi.fn();
  render(<ActionDialogue events={events} coordinator="research" language="en" writable busy={false} send={send}/>);
  expect(screen.getByRole("alert").textContent).toContain("Invalid conversation history");
  expect(screen.queryByRole("button", {name:"Reply"})).toBeNull();
  expect(screen.queryByLabelText("Message")).toBeNull();
  expect(screen.queryByText("Answer recorded")).toBeNull();
  expect(send).not.toHaveBeenCalled();
});
const question: DialogueEvent = { event_id:"question-0001", kind:"confirmation_request", text:"Which source?", coordinator:"research", actor:"coordinator:research", at:"2026-10-14", before_sha256:"a".repeat(64) };
it("links the answer to its exact question and does not claim execution", async()=>{
  const send=vi.fn().mockResolvedValue(true);
  render(<ActionDialogue events={[question]} coordinator="research" language="en" writable busy={false} send={send}/>);
  fireEvent.click(screen.getByRole("button",{name:"Reply"}));
  fireEvent.change(screen.getByLabelText("Message"),{target:{value:"Use the signed source"}});
  fireEvent.click(screen.getByRole("button",{name:"Record on card"}));
  await waitFor(()=>expect(send).toHaveBeenCalledTimes(1));
  expect(send.mock.calls[0][0]).toMatchObject({kind:"answer",reply_to:"question-0001",coordinator:"research",text:"Use the signed source"});
  expect(screen.getByText(/These messages do not indicate current executor activity/)).toBeTruthy();
});
it("keeps the draft after a conflict and renders content inertly", async()=>{
  const send=vi.fn().mockResolvedValue(false);
  render(<ActionDialogue events={[{...question,text:'<img src=x onerror=alert(1)>'}]} coordinator="research" language="en" writable busy={false} send={send}/>);
  expect(document.querySelector("img")).toBeNull();
  fireEvent.change(screen.getByLabelText("Message"),{target:{value:"My evidence"}});
  fireEvent.click(screen.getByRole("button",{name:"Record on card"}));
  await waitFor(()=>expect(send).toHaveBeenCalledTimes(1));
  expect((screen.getByLabelText("Message") as HTMLTextAreaElement).value).toBe("My evidence");
});
it("does not offer self answers, terminal writes, or replies to answered questions",()=>{
  render(<ActionDialogue events={[question,{...question,event_id:"answer-0001",kind:"answer",reply_to:question.event_id,actor:"operator"}]} coordinator="research" language="en" writable={false} busy={false} send={vi.fn()}/>);
  expect(screen.queryByRole("button",{name:"Reply"})).toBeNull();
  expect(screen.queryByLabelText("Message")).toBeNull();
});
it.each([{}, [null], ["broken"], [{kind:"question",text:{bad:"object"}}], [{...question,event_id:undefined}], false, 0])("keeps malformed dialogue inert without crashing the card: %j", (events)=>{
  const send=vi.fn();
  render(<ActionDialogue events={events as unknown as DialogueEvent[]} coordinator="research" language="en" writable busy={false} send={send}/>);
  expect(screen.getByRole("alert").textContent).toContain("Invalid conversation history");
  expect(screen.queryByRole("button",{name:"Record on card"})).toBeNull();
  expect(send).not.toHaveBeenCalled();
});

it('uses page titles for display while preserving exact events and keeping local file references inert',()=>{
  const events=[{...question,text:'Summarize `project-id`?'},{...question,event_id:'answer-0001',kind:'answer',reply_to:question.event_id,actor:'operator',text:'project-id'},{...question,event_id:'comment-0001',kind:'comment',text:'Resumo local: /private/summary.md\nSHA-256: '+'b'.repeat(64)}];
  const original=JSON.stringify(events);
  const send=vi.fn();
  render(<ActionDialogue events={events} coordinator="research" coordinatorLabel="Research" pages={[{id:'project-id',title:'Project Alpha'} as never]} language="en" writable={false} busy={false} send={send}/>);
  expect(screen.getByText('Project Alpha',{selector:'p'})).toBeTruthy();
  expect(screen.getByText('Research · Request confirmation')).toBeTruthy();
  expect(screen.getByText('project-id',{selector:'details p'})).toBeTruthy();
  expect(screen.getAllByText('Original record and details')).toHaveLength(3);
  expect(screen.getByText(/Local summary reference recorded/)).toBeTruthy();
  expect(document.querySelector('a')).toBeNull();
  expect(JSON.stringify(events)).toBe(original);
  expect(send).not.toHaveBeenCalled();
});
