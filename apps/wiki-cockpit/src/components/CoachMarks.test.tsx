// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import { CoachMarks } from "./CoachMarks";

afterEach(() => {
  cleanup();
  configureLanguage("en");
  try {
    window.localStorage?.clear();
  } catch {
    // The isolated jsdom document may have an opaque origin; this component
    // already treats unavailable storage as a supported private-mode case.
  }
});

describe("CoachMarks keyboard flow", () => {
  it("advances exactly one step when Enter activates the focused Next button", () => {
    configureLanguage("en");
    render(<CoachMarks open onClose={vi.fn()} />);

    const next = screen.getByRole("button", { name: "Next" });
    next.focus();
    fireEvent.keyDown(next, { key: "Enter" });
    fireEvent.click(next);

    expect(screen.getByRole("dialog", { name: "First choose the question" })).toBeTruthy();
    expect(screen.getByText("2 of 7")).toBeTruthy();
  });

  it("returns focus to the real opener after the auto-focused tour closes", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      const openerRef = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={openerRef} onClick={() => setOpen(true)} type="button">
            Open guide
          </button>
          <CoachMarks
            open={open}
            returnFocusTo={openerRef.current}
            onClose={() => setOpen(false)}
          />
        </>
      );
    }

    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open guide" });
    opener.focus();
    fireEvent.click(opener);

    expect(screen.getByRole("button", { name: "Next" })).toBe(document.activeElement);
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
