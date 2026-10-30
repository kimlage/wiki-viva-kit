// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import { InformationNotice } from "./InformationNotice";

afterEach(() => { cleanup(); configureLanguage("en"); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
it("keeps the original observation date and describes the current-use condition without refreshing", () => {
  configureLanguage("pt");
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<InformationNotice frontmatter={{ verified_at: "2026-01-01", information_requirements: [
    {target:"claim-balance",fields:["amount"],temporal:"current",max_age_days:1}
  ] }} />);
  expect(screen.getByText("Verificação registrada: 2026-01-01")).toBeTruthy();
  expect(screen.getByText("A informação atual precisa estar verificada antes da execução.")).toBeTruthy();
  expect(screen.getByText("claim-balance")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
it("presents historical use with its observation limit", () => {
  render(<InformationNotice frontmatter={{ information_requirements: [
    {target:"historical-claim",fields:["body"],temporal:"historical",max_age_days:0}
  ] }} />);
  expect(screen.getByText("Historical reading preserves the original observation date.")).toBeTruthy();
  expect(screen.getByText("No factual verification is recorded here.")).toBeTruthy();
});

it("shows the actual target verification and concrete impediment without fetching", () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<InformationNotice frontmatter={{}} assessment={{ consumer: "action", ready: false,
    assessed_at: "2026-10-30T12:00:00Z", permission_granted: false, relation_errors: [],
    requirements: [{ target: "specific-claim", fields: ["amount"], temporal: "current", verified_at: "2026-01-01",
      valid_until: "2026-01-02T23:59:59Z", blockers: ["information_verification_expired"], ready: false }] }} />);
  expect(screen.getByText("Information pending verification for this use.")).toBeTruthy();
  expect(screen.getByText("Verification recorded: 2026-01-01")).toBeTruthy();
  expect(screen.getByText("specific-claim · amount")).toBeTruthy();
  expect(screen.getByText("The observation falls outside the required validity.")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});

it("does not present an expired static assessment as ready", () => {
  vi.spyOn(Date,"now").mockReturnValue(Date.parse("2026-11-01T12:00:00Z"));
  render(<InformationNotice frontmatter={{}} assessment={{ consumer: "action", ready: true,
    assessed_at: "2026-10-30T12:00:00Z", permission_granted: false, relation_errors: [],
    requirements: [{ target: "claim", fields: ["body"], temporal: "current", verified_at: "2026-10-30",
      valid_until: "2026-10-31T12:00:00Z", blockers: [], ready: true }] }} />);
  expect(screen.getByText("Information pending verification for this use.")).toBeTruthy();
});

it("shows expiry while the same reader remains open without fetching", () => {
  vi.useFakeTimers();vi.setSystemTime("2026-10-30T12:00:00Z");
  const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
  render(<InformationNotice frontmatter={{}} assessment={{ consumer: "action", ready: true,
    assessed_at: "2026-10-30T12:00:00Z", permission_granted: false, relation_errors: [],
    requirements: [{ target: "claim", fields: ["body"], temporal: "current", verified_at: "2026-10-30",
      valid_until: "2026-10-30T12:00:01Z", blockers: [], ready: true }] }} />);
  expect(screen.getByText("The declared information met its requirements at assessment. Execution checks again.")).toBeTruthy();
  act(() => vi.advanceTimersByTime(1002));
  expect(screen.getByText("Information pending verification for this use.")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
