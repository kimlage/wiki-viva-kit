// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GateChecks } from "./GateChecks";
import { GatesDock } from "./GatesDock";
import type { GateRecord, SnapshotBundle } from "../types";

const audit: GateRecord = { id: "wiki_audit", status: "not_run", argv: ["python3", "scripts/wiki_audit.py", "--check"] };
const unavailable: GateRecord = { id: "pytest", status: "not_run", argv: ["python3", "-m", "pytest", "tests/"], available: false, unavailable_reason: "installed_gate_unavailable" };
afterEach(() => cleanup());

it("disables unavailable gate and skips it in Run checks while retaining permitted gates", async () => {
  const runGate = vi.fn().mockResolvedValue({ ok: true, returncode: 0, stdout: "ok" });
  render(<GateChecks gates={[audit, unavailable]} runGate={runGate} onNotice={vi.fn()} onRefetch={vi.fn()} />);
  const disabled = screen.getByRole("button", { name: /Run Tests — unavailable/i }) as HTMLButtonElement;
  expect(disabled.disabled).toBe(true);
  expect(disabled.title).toMatch(/installed-code mode/i);
  expect(screen.getByText("unavailable")).toBeTruthy();
  fireEvent.click(disabled);
  fireEvent.click(screen.getByRole("button", { name: "Run checks" }));
  await waitFor(() => expect(runGate).toHaveBeenCalledTimes(1));
  expect(runGate).toHaveBeenCalledWith("wiki_audit");
});

it("unavailable overrides an earlier session pass and is counted separately", async () => {
  const runGate = vi.fn().mockResolvedValue({ ok: true, returncode: 0, stdout: "ok", finished_at: "2026-11-03T10:00:00Z" });
  const previous: GateRecord = { ...unavailable, available: true, status: "not_run" };
  const props = { runGate, onNotice: vi.fn(), onRefetch: vi.fn() };
  const view = render(<GateChecks gates={[previous]} {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  await waitFor(() => expect(screen.getByText("passed")).toBeTruthy());
  view.rerender(<GateChecks gates={[{ ...unavailable, status: "pass", finished_at: "2026-11-03T10:00:00Z" }]} {...props} />);
  expect(screen.queryByText("passed")).toBeNull();
  expect(screen.queryByText("2026-11-03 10:00")).toBeNull();
  expect((screen.getByRole("button", { name: /Run Tests — unavailable/i }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Run checks" }) as HTMLButtonElement).disabled).toBe(true);
  view.unmount();
  const bundle = { gates: { status: "partial", gates: [audit, unavailable] } } as unknown as SnapshotBundle;
  render(<GatesDock bundle={bundle} runGate={runGate} onNotice={vi.fn()} onRefetch={vi.fn()} onClose={vi.fn()} />);
  const rail = screen.getByLabelText("Checks visual summary");
  expect(within(rail).getByText("unavailable").parentElement?.textContent).toContain("1");
  expect(within(rail).getByText("not run").parentElement?.textContent).toContain("1");
});


it("does not paint a session result as current validation in installed mode", async () => {
  const runGate = vi.fn().mockResolvedValue({ ok: true, returncode: 0, finished_at: "2026-11-03T10:00:00Z", stdout: "ok" });
  const historical: GateRecord = { ...audit, status: "not_run", finished_at: null, current_validation_supported: false };
  const props = { runGate, onNotice: vi.fn(), onRefetch: vi.fn() };
  const view = render(<GateChecks gates={[historical]} {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  await waitFor(() => expect(runGate).toHaveBeenCalled());
  view.rerender(<GateChecks gates={[{ ...historical, historical_receipt: true }]} {...props} />);
  expect(screen.getByText("A historical receipt does not validate the current content.")).toBeTruthy();
  expect(screen.queryByText("passed")).toBeNull();
  expect(screen.getByText("not run")).toBeTruthy();
  expect(screen.queryByText("2026-11-03 10:00")).toBeNull();
});
