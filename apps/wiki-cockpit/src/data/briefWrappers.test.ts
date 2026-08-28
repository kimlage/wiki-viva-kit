// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveBriefText } from "./snapshot";
import { resetOperatorSecurityForTests } from "../world/clients/operatorClient";

let response: { ok: boolean; status?: number; json: () => Promise<unknown> };

beforeEach(() => {
  resetOperatorSecurityForTests();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("wiki-cockpit.config.json")) {
        return { ok: true, json: async () => ({ api_base: "/api", mode: "local_operator" }) };
      }
      if (String(url).endsWith("/api/health")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            server_version: "wiki_web_server.v6",
            schema_capabilities: [
              "operator_security_v2",
              "cors_default_deny_v1",
              "action_state_transitions_v1"
            ],
            operator_security: {
              version: "wiki_operator_security.v2",
              nonce_header: "X-Wiki-Operator-Nonce",
              nonce: "test-nonce",
              attempt_header: "X-Wiki-Attempt-Key",
              max_body_bytes: 1_048_576,
              mutations: "post_only",
              browser_origin_default: "deny",
              cors_opt_in: "exact_loopback_allowlist"
            }
          })
        };
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
