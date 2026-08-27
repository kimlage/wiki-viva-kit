// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BriefStudio } from "./BriefStudio";
import type { BriefRecord, CodexCapability } from "../types";

afterEach(cleanup);

const brief = (over: Partial<BriefRecord> = {}): BriefRecord => ({
  brief_id: "b123",
  status: "draft",
  spec: { grounding: {} },
  brief_sha: "sha",
  size_chars: 10,
  snapshot_generated_at: "2026-07-01",
  target_paths: [],
  context_pages: [],
  job_id: null,
  text: "# Work brief\n\n## 5 · Output contract\n- never merge\n",
  ...over
});

const cap = (over: Partial<CodexCapability> = {}): CodexCapability => ({
  enabled: true,
  installed: false,
  runnable: false,
  authed: false,
  auth_mode: null,
  version: null,
  usable: false,
  reason: "Codex is not installed",
  ...over
});

function noop() {
  /* no-op */
}

describe("BriefStudio", () => {
  it("shows the full composed brief in an editable field", () => {
    render(
      <BriefStudio brief={brief()} capability={cap()} busy={false} onSaveText={noop} onDiscard={noop} onNotice={noop} onClose={noop} />
    );
    const area = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(area.value).toContain("Output contract");
  });

  it("keeps Save disabled until the text is edited", () => {
    const onSaveText = vi.fn();
    render(
      <BriefStudio brief={brief()} capability={cap()} busy={false} onSaveText={onSaveText} onDiscard={noop} onNotice={noop} onClose={noop} />
    );
    const save = screen.getByRole("button", { name: /Save edits/ }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "edited" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(onSaveText).toHaveBeenCalledWith("b123", "edited");
  });

  it("disables Execute with an honest reason when Codex is not usable", () => {
    render(
      <BriefStudio
        brief={brief()}
        capability={cap({ reason: "Codex is not installed" })}
        busy={false}
        onSaveText={noop}
        onDiscard={noop}
        onExecute={vi.fn()}
        onNotice={noop}
        onClose={noop}
      />
    );
    const execute = screen.getByRole("button", { name: /Execute with Codex/ }) as HTMLButtonElement;
    expect(execute.disabled).toBe(true);
    expect(execute.getAttribute("title")).toContain("not installed");
  });

  it("enables Execute only when Codex is usable and a handler exists", () => {
    const onExecute = vi.fn();
    render(
      <BriefStudio
        brief={brief()}
        capability={cap({ usable: true, installed: true, runnable: true, authed: true, reason: "" })}
        busy={false}
        onSaveText={noop}
        onDiscard={noop}
        onExecute={onExecute}
        onNotice={noop}
        onClose={noop}
      />
    );
    const execute = screen.getByRole("button", { name: /Execute with Codex/ }) as HTMLButtonElement;
    expect(execute.disabled).toBe(false);
    fireEvent.click(execute);
    expect(onExecute).toHaveBeenCalled();
  });

  it("uses the Claude capability when the brief selects the Claude adapter", () => {
    const onExecute = vi.fn();
    render(
      <BriefStudio
        brief={brief({ spec: { agent: "claude", grounding: {} } })}
        capability={cap({ usable: false, reason: "Codex unavailable" })}
        claudeCapability={cap({ usable: true, installed: true, runnable: true, authed: true, reason: "" })}
        busy={false}
        onSaveText={noop}
        onDiscard={noop}
        onExecute={onExecute}
        onNotice={noop}
        onClose={noop}
      />
    );
    const execute = screen.getByRole("button", { name: /Execute with Claude/ }) as HTMLButtonElement;
    expect(execute.disabled).toBe(false);
    fireEvent.click(execute);
    expect(onExecute).toHaveBeenCalled();
  });

  it("copies the current text and notifies", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const onNotice = vi.fn();
    render(
      <BriefStudio brief={brief()} capability={cap()} busy={false} onSaveText={noop} onDiscard={noop} onNotice={onNotice} onClose={noop} />
    );
    fireEvent.click(screen.getByRole("button", { name: /Copy prompt/ }));
    await Promise.resolve();
    expect(writeText).toHaveBeenCalled();
  });

  it("discards via the handler", () => {
    const onDiscard = vi.fn();
    render(
      <BriefStudio brief={brief()} capability={cap()} busy={false} onSaveText={noop} onDiscard={onDiscard} onNotice={noop} onClose={noop} />
    );
    fireEvent.click(screen.getByRole("button", { name: /Discard/ }));
    expect(onDiscard).toHaveBeenCalledWith("b123");
  });
});
