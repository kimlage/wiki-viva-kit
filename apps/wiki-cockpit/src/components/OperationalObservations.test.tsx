// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { RuntimeObservations } from "../data/runtimeObservations";
import type { PageRecord, SourceEntity } from "../types";
import type { WorkFront } from "../data/actionBoard";
import { RuntimeObservationPanel } from "./RuntimeObservationPanel";
import { SourceObservationSummary } from "./SourceObservationSummary";
import { WorkFronts } from "./WorkFronts";
import { ActionAccessRequirements } from "./ActionAccessRequirements";
import { sourceTelemetry, streamFreshnessLabel } from "./sourceDockModel";

afterEach(() => { cleanup(); configureLanguage("en"); });
const field = (label: string) => screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;

it("keeps event-driven no-pending telemetry neutral without inventing a recurring cadence or completed capture", () => {
  const source = { sync: { streams_total: 1, streams_fresh: 1, streams_without_pending: 1 }, pending_streams: 0, recipe_ok: true } as SourceEntity;
  const item = sourceTelemetry([source]).find(row => row.key === "fresh");
  expect(item).toMatchObject({ label: "no pending trigger", value: "1/1", tone: "muted" });
  const stream = { selected: true, cursor_age_days: 22, cadence_days: 0 } as SourceEntity["streams"][number];
  expect(streamFreshnessLabel(stream, "event_driven")).toContain("last capture");
  expect(streamFreshnessLabel(stream, "event_driven")).not.toContain("every");
  expect(streamFreshnessLabel({ ...stream, filters: { processing_state: "needs_review" } }, "event_driven")).toContain("needs_review");
  expect(streamFreshnessLabel({ ...stream, cursor_age_days: null }, "one_shot")).not.toContain("capture complete");
});
function observation(): RuntimeObservations {
  return {
    ok: true, schema_version: "wiki_runtime_observations.v1", observed_at: "2026-10-31T12:00:00Z",
    operator: { started_at: "2026-10-30T09:00:00Z", boot_source_commit: "code-before", current_source_commit: "code-current", content_source_commit: "content-current", restart_required: true, server_version: "wiki_web_server.v11", frontend: { status: "observed", entry_sha256: "served-hash", source_commit: null } },
    openclaw: { configured: true, observation_scope: "retained_local_evidence", gateway_status: "not_observed", active_run: null, pending_inputs: null,
      usage: { status: "not_measured", tokens: null, cost: null }, native_observations: [], errors: [], rules: [],
      transport: { status: "reachable", scope: "loopback_tcp_only", observed_at: "2026-10-31T11:59:00Z" },
      attempts: [{ profile: "research", action_id: "first", effect_key: "attempt-a", attempted_at: "2026-10-29T10:00:00Z", result_captured_at: null, status: "awaiting_reconciliation" },
        { profile: "research", action_id: "second", effect_key: "attempt-b", attempted_at: "2026-10-30T10:00:00Z", result_captured_at: "2026-10-30T11:00:00Z", status: "result_retained" }]
    }
  };
}

it("scopes retained attempts to the selected action and keeps reachability, liveness and versions separate", () => {
  const value = observation();
  value.operator.boot_code_sha256 = "a".repeat(64); value.operator.current_code_sha256 = "b".repeat(64);
  render(<RuntimeObservationPanel observation={value} actionId="first" snapshotId="snapshot-a" versions />);
  expect(field("Last attempt")).toBe("2026-10-29T10:00:00Z");
  expect(field("Retained status")).toContain("live execution unknown");
  expect(field("Result captured")).toBe("Not observed");
  expect(field("Tokens / cost")).toBe("Not measured");
  expect(field("Live execution / pending inputs")).toBe("Not observed");
  expect(field("Local TCP transport only")).toBe("Listener reachable");
  expect(screen.getByText(/does not verify Gateway identity/)).toBeTruthy();
  expect(field("Content checkout")).toBe("content-current");
  expect(field("Current code checkout")).toBe("code-current");
  expect(field("Checkout at process start")).toBe("code-before");
  expect(field("Code SHA-256 at process start")).toBe("a".repeat(64));
  expect(field("Current code SHA-256")).toBe("b".repeat(64));
  expect(field("Served entry hash")).toBe("served-hash");
  expect(field("Frontend source commit")).toBe("Not observed");
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText("2026-10-30T11:00:00Z")).toBeNull();
});

it("keeps receipt adoption distinct from content incorporation and a failed wake distinct from no dispatch", () => {
  const value = observation();
  value.openclaw.attempts[0].proposal = { status: "received_in_main", branch: "wiki/result", head: "h", proposal_head: "p", approved_base: "b", material_path: "result.md", material_sha256: "s", content_incorporated_in_main: false };
  Object.assign(value.openclaw.attempts[0], {
    run_id: "attempt-a", result: { excerpt: "Existing synthetic result <script>untrusted</script>", text_sha256: "a".repeat(64), truncated: true },
    authorization: { status: "not_observed" },
    guard_admission: { status: "retained_chain_verified", model: "synthetic-model", effort: "high", error_code: null },
    review: { status: "not_observed", head: null }
  });
  value.openclaw.rules = [{ rule_id: "daily-check", profile: "research", action_id: "first", interval_minutes: 1440, scheduler_status: "not_observed", next_expected_observation_at: "2026-11-01T09:00:00Z", last_wake: { observed_at: "2026-10-31T09:00:00Z", slot: 1, mode: "dispatch", effect_key: null, status: "failure", error_code: "observation_failed", new_dispatch: null } }];
  render(<RuntimeObservationPanel observation={value} actionId="first" />);
  expect(field("Wiki incorporation")).toContain("content incorporation not proved");
  expect(field("Run / receipt ID")).toBe("attempt-a");
  expect(field("Current authorization")).toBe("Not observed");
  expect(field("Independent review")).toBe("Not observed");
  expect(field("Retained admission")).toContain("Historical");
  expect(field("Admitted model / effort")).toBe("synthetic-model / high");
  expect(screen.getByText("Existing synthetic result <script>untrusted</script>").tagName).toBe("PRE");
  expect(screen.getByText(/hash identifies the full retained text/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
  expect(field("Wake result")).toBe("Failure recorded");
  expect(field("New dispatch in this wake")).toBe("Not observed");
  expect(screen.getByText(/scheduler activity unverified/)).toBeTruthy();
});

it("does not turn an unavailable observation or an empty retained scope into inactivity", () => {
  const { rerender } = render(<RuntimeObservationPanel observation={null} unavailable />);
  expect(screen.queryByText(/No retained attempt/)).toBeNull();
  expect(screen.getByRole("status").textContent).toContain("Observation unavailable");
  const value = observation(); value.openclaw.attempts = [];
  rerender(<RuntimeObservationPanel observation={value} />);
  expect(screen.getByText(/This does not prove inactivity/)).toBeTruthy();
});

it("separates event-driven source ingestion, later verification, pending adoption and live access", () => {
  const source = { pending_streams: 0, updated_at: "2026-10-31", sync: { event_closure: { gate_state: "pending" } }, lifecycle: { last_ingested_at: "2026-10-09", adoption_state: "pending", pipeline_stage: "gate_pending" }, verification: { recorded_at: "2026-10-29", evidence_refs: ["check"], live_access: "unknown" } } as unknown as SourceEntity;
  const open = vi.fn();
  render(<SourceObservationSummary source={source} pages={[{ id: "check", path: "memories/check.md", title: "Bounded readback" } as PageRecord]} open={open} />);
  expect(field("Recorded pending work")).toBe("No recorded trigger pending");
  expect(field("Last recorded ingestion")).toBe("2026-10-09");
  expect(field("Recorded verification")).toBe("2026-10-29");
  expect(field("Wiki adoption")).toBe("pending");
  expect(field("Incorporation gate")).toBe("pending");
  expect(field("Current access / effective identity")).toBe("Unknown");
  expect(screen.queryByText("2026-10-31")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Bounded readback" }));
  expect(open).toHaveBeenCalledWith("check");
});

it("filters action requirements while keeping profile requirements and effective access unverified", () => {
  render(<ActionAccessRequirements actionId="first" requirements={[
    { service: "Storage", expected_identity: "reviewer@example.com", method: "existing account", source_ref: "scope" },
    { service: "Archive", expected_identity: "researcher@example.com", method: "read only", source_ref: "scope", action_ids: ["first"], operation: "Read historical note", resource: "Approved note", recovery: "Review account selection" },
    { service: "Unrelated service", expected_identity: "other@example.com", method: "read", source_ref: "other", action_ids: ["second"] }
  ]} />);
  expect(screen.getByText("Profile requirement · Storage")).toBeTruthy();
  expect(screen.getByText("Requirement for this action · Archive · Read historical note")).toBeTruthy();
  expect(screen.queryByText(/Unrelated service/)).toBeNull();
  expect(screen.getAllByText(/Effective identity and current access: not verified/)).toHaveLength(2);
});

it("projects fronts as documented context with existing action and evidence links, without a second queue", () => {
  const front: WorkFront = { page_id: "front", path: "memories/front.md", title: "Research front", page_type: "project", context: "research", declared_status: "active", recorded_at: "2026-10-29", owner_ref: "owner", coordinators: ["research"], action_ids: ["first"], active_action_ids: ["first"], evidence_refs: ["check"], source_refs: [], next_action: "Review historical evidence", blocker_reason: "Paused until explicitly resumed", summary: "Scoped research", content_sha256: "a".repeat(64), live_execution: "unknown" };
  const pages = [{ id: "front", title: "Research front", path: front.path }, { id: "first", title: "Existing action", path: "memories/first.md" }, { id: "check", title: "Latest evidence", path: "memories/check.md" }] as PageRecord[];
  const open = vi.fn();
  const { rerender } = render(<WorkFronts fronts={[front]} pages={pages} open={open} profiles={[{ id: "research", label: "Research coordinator", scope: "Historical synthesis only; no external browsing." }]} />);
  expect(screen.getByText(/do not authorize resumption/)).toBeTruthy();
  expect(field("Recorded state")).toBe("active");
  expect(field("Last page record")).toBe("2026-10-29");
  expect(screen.getByText(/Live execution and effective access: unknown/)).toBeTruthy();
  expect(screen.getByText(/Historical synthesis only/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Existing action" }));
  expect(open).toHaveBeenCalledWith("first", expect.any(HTMLElement));
  expect(screen.queryByRole("combobox")).toBeNull();
  rerender(<WorkFronts pages={pages} open={open} />);
  expect(within(screen.getByRole("region", { name: "Work fronts" })).getByRole("status").textContent).toContain("unavailable");
  expect(screen.queryByText("No front is declared in this projection.")).toBeNull();
});
