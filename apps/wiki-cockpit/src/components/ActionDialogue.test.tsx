// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ActionDialogue } from "./ActionDialogue";
import type { DialogueEvent } from "../data/actionBoard";
afterEach(cleanup);
const question: DialogueEvent = { event_id:"question-0001", kind:"confirmation_request", text:"Which source?", coordinator:"research", actor:"coordinator:research", at:"2026-10-14", before_sha256:"a".repeat(64) };
it("links the answer to its exact question and does not claim execution", async()=>{
  const send=vi.fn().mockResolvedValue(true);
  render(<ActionDialogue events={[question]} coordinator="research" language="en" writable busy={false} send={send}/>);
  fireEvent.click(screen.getByRole("button",{name:"Reply"}));
  fireEvent.change(screen.getByLabelText("Message"),{target:{value:"Use the signed source"}});
  fireEvent.click(screen.getByRole("button",{name:"Record on card"}));
  await waitFor(()=>expect(send).toHaveBeenCalledTimes(1));
  expect(send.mock.calls[0][0]).toMatchObject({kind:"answer",reply_to:"question-0001",coordinator:"research",text:"Use the signed source"});
  expect(screen.getByText(/Delivery and resumption still require/)).toBeTruthy();
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
