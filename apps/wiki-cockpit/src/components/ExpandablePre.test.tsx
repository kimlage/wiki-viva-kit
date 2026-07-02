// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ExpandablePre } from "./ExpandablePre";

afterEach(cleanup);

const long = Array.from({ length: 40 }, (_, i) => `line ${i} with some content`).join("\n");

describe("ExpandablePre", () => {
  it("clamps inline and opens the full content in a modal on expand", () => {
    render(<ExpandablePre text={long} title="Honesty audit" />);
    // Inline body is present but clamped (CSS); Expand is offered for long text.
    const expand = screen.getByRole("button", { name: /Expand/ });
    fireEvent.click(expand);
    const modal = screen.getByRole("dialog", { name: "Honesty audit" });
    expect(modal).toBeTruthy();
    expect(modal.textContent).toContain("line 39 with some content");
  });

  it("offers no Expand for short output (a two-line result needs no modal)", () => {
    render(<ExpandablePre text={"ok\ndone"} title="short" />);
    expect(screen.queryByRole("button", { name: /Expand/ })).toBeNull();
  });

  it("shows the empty label when there is no output", () => {
    render(<ExpandablePre text="" title="empty" emptyLabel="No output." />);
    expect(screen.getByText("No output.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Expand/ })).toBeNull();
  });
});
