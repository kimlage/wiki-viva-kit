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

afterEach(() => { cleanup(); configureLanguage("en"); vi.useRealTimers(); });
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

  };
}

it("keeps observed content, process and bundle versions separate without claiming execution authority", () => {
  const value = observation();
  value.operator.boot_code_sha256 = "a".repeat(64); value.operator.current_code_sha256 = "b".repeat(64);
  render(<RuntimeObservationPanel observation={value} snapshotId="snapshot-a" versions />);
  expect(field("Content checkout")).toBe("content-current");
  expect(field("Current code checkout")).toBe("code-current");
  expect(field("Checkout at process start")).toBe("code-before");
  expect(field("Code SHA-256 at process start")).toBe("a".repeat(64));
  expect(field("Current code SHA-256")).toBe("b".repeat(64));
  expect(field("Served entry hash")).toBe("served-hash");
  expect(field("Frontend source commit")).toBe("Not observed");
  expect(screen.getByText(/restart required/)).toBeTruthy();
  expect(screen.getByText(/Refresh does not perform either operation/)).toBeTruthy();
  expect(screen.getByText(/scheduler installation are not observed/)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("keeps unavailable observations explicit and does not infer a restart from missing data", () => {
  render(<RuntimeObservationPanel observation={null} unavailable versions />);
  expect(screen.getByRole("status").textContent).toContain("Observation unavailable");
  expect(field("Observed at")).toBe("Not observed");
  expect(screen.queryByText(/restart required/)).toBeNull();
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
