// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveBriefText } from "./snapshot";

let response: { ok: boolean; status?: number; json: () => Promise<unknown> };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("wiki-cockpit.config.json")) {
        return { ok: true, json: async () => ({ api_base: "/api", mode: "local_operator" }) };
      }
      return response;
    })
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("saveBriefText fail-closed", () => {
  it("throws on an ok:false rejection even when a brief_id is present", async () => {
    // The server refuses a non-draft edit with ok:false + brief_id.
    response = {
      ok: false,
      status: 400,
      json: async () => ({ ok: false, brief_id: "b1", error: "only draft briefs can be edited" })
    };
    await expect(saveBriefText("b1", "x")).rejects.toThrow(/only draft/);
  });

  it("returns the saved record on success", async () => {
    response = {
      ok: true,
      json: async () => ({ ok: true, brief_id: "b1", brief_sha: "newsha", status: "draft", text: "x" })
    };
    const saved = await saveBriefText("b1", "x");
    expect(saved.brief_sha).toBe("newsha");
  });
});
