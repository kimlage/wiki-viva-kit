import { describe, expect, it } from "vitest";
import type { SourceStream } from "../types";
import { groupSourceStreams, streamCategory } from "./sourceDockModel";

function stream(id: string, label: string, issueTypes?: unknown): SourceStream {
  return { id, label, selected: true, privacy: "public", target_pages: [], skip_reason: "",
    cursor_age_days: null, cadence_days: 7, breached: false,
    ...(issueTypes === undefined ? {} : { filters: { issue_types: issueTypes } }) };
}

describe("source stream navigation categories", () => {
  it("groups synthetic Jira and Calendar metadata in fixed order without changing streams", () => {
    const items = [stream("calendar-ritual", "Weekly ritual"), stream("board", "Board", ["Epic"]),
      stream("issues", "Issues", ["Task", "Bug"]), stream("projects", "Projects", ["Project"])];
    const before = structuredClone(items);
    expect(groupSourceStreams(items).map(group => group.category)).toEqual(["project", "epic", "cards", "ritual"]);
    expect(items).toEqual(before);
  });
  it("keeps mixed, unknown or invalid metadata in other", () => {
    expect(streamCategory(stream("x", "Mixed", ["Epic", "Task"]))).toBe("other");
    expect(streamCategory(stream("x", "Unknown", ["custom"]))).toBe("other");
    expect(streamCategory(stream("x", "Invalid", [42]))).toBe("other");
  });
});
