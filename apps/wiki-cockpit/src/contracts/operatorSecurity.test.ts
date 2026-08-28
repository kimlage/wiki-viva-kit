import { describe, expect, it } from "vitest";
import {
  operatorSecurityEvidence,
  REQUIRED_OPERATOR_CAPABILITIES,
  validateOperatorHandshake
} from "./operatorSecurity.js";

function validHealth() {
  return {
    ok: true,
    server_version: "wiki_web_server.v6",
    schema_capabilities: [...REQUIRED_OPERATOR_CAPABILITIES, "codex"],
    operator_security: {
      version: "wiki_operator_security.v2",
      nonce_header: "X-Wiki-Operator-Nonce",
      nonce: "local-process-nonce",
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only",
      browser_origin_default: "deny",
      cors_opt_in: "exact_loopback_allowlist"
    }
  };
}

describe("shared operator security contract", () => {
  it("returns a complete nonce-free release evidence projection", () => {
    const validation = validateOperatorHandshake(validHealth());
    expect(validation.errors).toEqual([]);
    expect(validation.ok).toBe(true);
    expect(operatorSecurityEvidence(validation)).toEqual({
      version: "wiki_operator_security.v2",
      nonce_present: true,
      nonce_header: "X-Wiki-Operator-Nonce",
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only",
      browser_origin_default: "deny",
      cors_opt_in: "exact_loopback_allowlist"
    });
  });

  it.each([
    ["old server", { server_version: "wiki_web_server.v4" }, "server version"],
    [
      "missing action transition",
      { schema_capabilities: ["operator_security_v2", "cors_default_deny_v1"] },
      "action_state_transitions_v1"
    ],
    [
      "malformed capability list",
      { schema_capabilities: [...REQUIRED_OPERATOR_CAPABILITIES, "operator_security_v2"] },
      "unique non-empty strings"
    ],
    ["missing security", { operator_security: undefined }, "security object"],
    ["old security", { operator_security: { ...validHealth().operator_security, version: "wiki_operator_security.v1" } }, "security version"],
    ["missing nonce", { operator_security: { ...validHealth().operator_security, nonce: "" } }, "nonce is missing"],
    ["wrong nonce header", { operator_security: { ...validHealth().operator_security, nonce_header: "X-Other" } }, "nonce header"],
    ["wrong attempt header", { operator_security: { ...validHealth().operator_security, attempt_header: "X-Other" } }, "attempt header"],
    ["unbounded body", { operator_security: { ...validHealth().operator_security, max_body_bytes: 1_048_577 } }, "max body bytes"],
    ["non-POST mutation", { operator_security: { ...validHealth().operator_security, mutations: "any" } }, "post_only"],
    ["open browser origin", { operator_security: { ...validHealth().operator_security, browser_origin_default: "allow" } }, "origin default"],
    ["wildcard CORS", { operator_security: { ...validHealth().operator_security, cors_opt_in: "wildcard" } }, "CORS opt-in"]
  ])("rejects %s", (_label, overrides, expected) => {
    const validation = validateOperatorHandshake({ ...validHealth(), ...overrides });
    expect(validation.ok).toBe(false);
    expect(validation.errors.join(" ")).toContain(expected);
  });

  it("never echoes malformed handshake values in diagnostics", () => {
    const secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456";
    const validation = validateOperatorHandshake({
      ...validHealth(),
      server_version: secret,
      operator_security: { ...validHealth().operator_security, version: secret, nonce: secret }
    });
    expect(JSON.stringify(validation.errors)).not.toContain(secret);
  });
});
