// @vitest-environment jsdom

// CommandBar interpretation layer (god-mode plan §10.1, §22.1): Enter on the
// focused input runs the command parser BEFORE search navigation; search,
// IME composition and the existing keyboard behavior stay untouched for
// anything the interpreter does not claim.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommandInvocation } from "../../commands/types";
import type { Instruments } from "../../data/surfaces";
import { parseRoute } from "../../router";
import type { WorldRoute } from "../../router";
import type { WorldCondition } from "../../scene/condition";
import { CommandBar, pushCommandHistory, stepCommandHistory } from "./CommandBar";

const INSTRUMENTS: Instruments = {
  worldEmpty: false,
  rootAnchorId: "root",
  searchEnabled: true,
  destinations: [],
  missionsEnabled: false,
  missionProviders: [],
  conditionEnabled: false,
  perspectives: ["quadrants"],
  defaultPerspective: "quadrants",
  hasQuadrants: true,
  createArrangement: "",
  createCatalog: [],
  intakeForms: [],
  adminSurfaceEnabled: false
};

const CONDITION: WorldCondition = {
  weather: "clear",
  freshRatio: 1,
  staleCount: 0,
  unknownCount: 0,
  gatesFailing: [],
  gatesNotRun: 0,
  pendingApproval: 0,
  pendingSourceIntake: 0,
  agentsActive: 0
};

function Harness({
  onCommand,
  onSearchKeyDown,
  drafts
}: {
  onCommand: (input: CommandInvocation) => void;
  onSearchKeyDown: (event: unknown) => void;
  drafts: string[];
}) {
  const [draft, setDraft] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const route = parseRoute("/w") as WorldRoute;
  return (
    <CommandBar
      route={route}
      showCompatibilityPerspectives={false}
      instruments={INSTRUMENTS}
      condition={CONDITION}
      changedCount={0}
      openMissionCount={0}
      trayOpen={false}
      missionsOpen={false}
      canComposeBrief={false}
      searchRef={searchRef}
      searchDraft={draft}
      searchExpanded={false}
      searchResultsId="search-results"
      onSearchDraft={(value) => {
        drafts.push(value);
        setDraft(value);
      }}
      onSearchKeyDown={onSearchKeyDown}
      onCommand={onCommand}
      onNavigateWorld={() => {}}
      onToggleTray={() => {}}
      onToggleMissions={() => {}}
      onOpenTour={() => {}}
    />
  );
}

function setup() {
  const onCommand = vi.fn();
  const onSearchKeyDown = vi.fn();
  const drafts: string[] = [];
  render(<Harness onCommand={onCommand} onSearchKeyDown={onSearchKeyDown} drafts={drafts} />);
  const input = screen.getByRole("combobox") as HTMLInputElement;
  return { onCommand, onSearchKeyDown, drafts, input };
}

afterEach(() => cleanup());

describe("CommandBar interpretation layer", () => {
  it("intercepts the ritual phrase on Enter before search and clears the field", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: " ABRACHAINDABRA " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).toHaveBeenCalledExactlyOnceWith({ kind: "easter_egg", id: "takezo_ritual" });
    expect(onSearchKeyDown).not.toHaveBeenCalled();
    expect(input.value).toBe("");
  });

  it("supports pasted invocations (interpretation reads the live value)", () => {
    const { onCommand, input } = setup();
    // A paste lands as a single change event; there is no per-key typing.
    fireEvent.change(input, { target: { value: "god_mode off" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).toHaveBeenCalledExactlyOnceWith({
      kind: "admin_command",
      commandId: "god_mode",
      args: { subcommand: "off" }
    });
  });

  it("keeps a near miss in the normal search flow", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "abrachaindabr" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).not.toHaveBeenCalled();
    expect(onSearchKeyDown).toHaveBeenCalledTimes(1);
    expect(input.value).toBe("abrachaindabr");
  });

  it("never triggers during IME composition", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "abrachaindabra" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(onCommand).not.toHaveBeenCalled();
    expect(onSearchKeyDown).toHaveBeenCalledTimes(1);
  });

  it("routes explicit invalid input to the host instead of search", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "> admin nope" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).toHaveBeenCalledExactlyOnceWith({
      kind: "invalid_command",
      messageKey: "command.invalid.unknown"
    });
    expect(onSearchKeyDown).not.toHaveBeenCalled();
  });

  it("recalls session history with ArrowUp only in explicit command mode", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "> admin overview" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.value).toBe("");

    fireEvent.change(input, { target: { value: "> " } });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.value).toBe("> admin overview");
    expect(onSearchKeyDown).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).toHaveBeenLastCalledWith({
      kind: "admin_command",
      commandId: "admin.overview",
      args: {}
    });
  });

  it("keeps arrow keys for search-result navigation outside command mode", () => {
    const { onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "finance" } });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(onSearchKeyDown).toHaveBeenCalledTimes(1);
    expect(input.value).toBe("finance");
  });

  it("returns from command mode to an empty search on Escape without consuming the ladder", () => {
    const { onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "> adm" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(onSearchKeyDown).not.toHaveBeenCalled();

    // Outside command mode, Escape still belongs to the existing search
    // handler (which itself feeds the tray → dock → reader → retreat ladder).
    fireEvent.change(input, { target: { value: "finance" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onSearchKeyDown).toHaveBeenCalledTimes(1);
  });

  it("delegates ordinary search Enter untouched", () => {
    const { onCommand, onSearchKeyDown, input } = setup();
    fireEvent.change(input, { target: { value: "finance overview" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommand).not.toHaveBeenCalled();
    expect(onSearchKeyDown).toHaveBeenCalledTimes(1);
  });
});

describe("command history helpers (plan §10.4)", () => {
  it("deduplicates consecutive entries and bounds the buffer", () => {
    const history: string[] = [];
    pushCommandHistory(history, "> admin overview");
    pushCommandHistory(history, "> admin overview");
    expect(history).toEqual(["> admin overview"]);
    for (let index = 0; index < 60; index += 1) pushCommandHistory(history, `> admin source plan s${index}`);
    expect(history.length).toBe(50);
    expect(history[history.length - 1]).toBe("> admin source plan s59");
  });

  it("walks older/newer and lands back on a fresh prompt", () => {
    const history = ["> admin overview", "> admin git status"];
    let step = stepCommandHistory(history, null, -1);
    expect(step).toEqual({ cursor: 1, value: "> admin git status" });
    step = stepCommandHistory(history, step.cursor, -1);
    expect(step).toEqual({ cursor: 0, value: "> admin overview" });
    step = stepCommandHistory(history, step.cursor, -1);
    expect(step).toEqual({ cursor: 0, value: "> admin overview" });
    step = stepCommandHistory(history, step.cursor, 1);
    expect(step).toEqual({ cursor: 1, value: "> admin git status" });
    step = stepCommandHistory(history, step.cursor, 1);
    expect(step).toEqual({ cursor: null, value: "" });
    expect(stepCommandHistory([], null, -1)).toEqual({ cursor: null, value: null });
    expect(stepCommandHistory(history, null, 1)).toEqual({ cursor: null, value: null });
  });
});
