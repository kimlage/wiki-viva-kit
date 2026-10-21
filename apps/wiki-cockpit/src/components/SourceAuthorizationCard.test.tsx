// @vitest-environment jsdom
// Synthetic projection/transport callbacks, never a real account or grant.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { SourceEntity, SourceAccess } from "../types";
import { SourceAuthorizationCard } from "./SourceAuthorizationCard";

beforeEach(() => { configureLanguage("en"); vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-20T12:00:00Z")); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const policy = { schema_version: "wiki_source_access.v1" as const, expected_identity: "reader@example.test", coordinator: "research", executor: "fictional-executor", requested_scopes: ["read"] };
const base: SourceAccess = { schema_version: "wiki_source_access.v1", binding_sha256: "a".repeat(64), status: "configured", verified: false,
  expected_identity: policy.expected_identity, confirmed_identity: "", coordinator: "research", executor: "fictional-executor", requested_scopes: ["read"], granted_scopes: [],
  checked_at: "", valid_until: "", evidence_ref: "", error_code: "", execution_ready: false, business_authority: "unknown" };
const source = { source_id: "fictional-source", title: "Fictional source", context: "research", updated_at: "2026-10-20", auth: { method: "mcp", ref: "example-connector", scopes: ["read"], note: "" }, access_policy: policy, access: base } as SourceEntity;
const verified: SourceAccess = { ...base, status: "verified", verified: true, confirmed_identity: policy.expected_identity, granted_scopes: ["read"], checked_at: "2026-10-20T11:59:00Z", valid_until: "2026-10-20T12:00:02Z", evidence_ref: "receipt:fictional-001" };
function panel(access?: SourceAccess, extra = {}) {
  return <SourceAuthorizationCard source={source} access={access} agentName="Example agent" agentCapabilitiesKnown agentReady connectorReady
    route={{ mode: "deterministic_connector", argv: [], mcp_hint: "", how_to_export: "", runnable: true }} {...extra} />;
}

it("configuration and capability do not prove live access or offer a fake grant", () => {
  render(panel(base));
  expect(screen.queryByText("Access verified")).toBeNull();
  expect(screen.getByText(/No supported connection or permission-grant action/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /grant|disconnect|revoke|connect/i })).toBeNull();
  expect(screen.getByText("fictional-executor")).toBeTruthy();
});
it("only offers an existing supported callback, without claiming its result", () => {
  const callback = vi.fn(); render(panel(base, { onRevalidate: callback }));
  fireEvent.click(screen.getByRole("button", { name: "Test access in this executor" }));
  expect(callback).toHaveBeenCalledOnce();
  expect(screen.queryByText("Access verified")).toBeNull();
});
it("expires displayed evidence without requiring a reload", () => {
  render(panel(verified)); expect(screen.getByText("Access verified")).toBeTruthy();
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.queryByText("Access verified")).toBeNull();
  expect(screen.getByText("Evidence expired or unknown")).toBeTruthy();
});
it("rejects evidence from another account/context binding and clears a failed probe", () => {
  const { rerender } = render(panel({ ...verified, binding_sha256: "b".repeat(64) }));
  expect(screen.queryByText("Access verified")).toBeNull();
  rerender(panel(verified, { probeFailed: true }));
  expect(screen.getByText("Technical blocker")).toBeTruthy();
  expect(screen.queryByText("Access verified")).toBeNull();
});
it.each(["awaiting_auth", "awaiting_approval", "authority_blocked", "execution_unknown", "revoked", "identity_mismatch"])("preserves explicit %s without an automatic reconnect", (status) => {
  render(panel({ ...verified, status, verified: false }));
  expect(screen.queryByText("Access verified")).toBeNull();
  expect(screen.queryAllByRole("button")).toHaveLength(0);
});

it.each(["wrong_account", "executor_unavailable", "session_expired", "authorization_missing"])("keeps %s distinct without granting access", (status) => {
  render(panel({ ...base, status }));
  expect(screen.queryByText("Access verified")).toBeNull();
  expect(screen.queryByRole("button", { name: /grant|login|connect/i })).toBeNull();
});
it("compact header cannot infer a connection from an account recipe", () => {
  render(panel(base, { compact: true }));
  expect(screen.getByText(/Connection:/)).toBeTruthy();
  expect(screen.queryByText(/Access verified/)).toBeNull();
});

it('renders the actual first-setup empty policy payload without claiming access',()=>{
 const empty={...source,access_policy:{} as SourceEntity['access_policy'],access:{...base,status:'not_configured'}};
 render(<SourceAuthorizationCard source={empty} access={empty.access} agentName="Example agent" agentCapabilitiesKnown={false} agentReady={false} connectorReady={false}/>);
 expect(screen.getByText('Authorization and live access')).toBeTruthy();
 expect(screen.queryByText('Access verified')).toBeNull();
});
