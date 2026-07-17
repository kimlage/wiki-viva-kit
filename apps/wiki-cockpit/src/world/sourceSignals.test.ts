// @vitest-environment jsdom

// Ephemeral scene<->dock signals (§12.3/§12.6): round-trip through the window
// event channel, unsubscribe hygiene, and the derived->recipe stream id
// resolution that keeps derived ids out of the dock DOM and the URL.

import { describe, expect, it, vi } from "vitest";
import type { SourceFoundationPayload } from "../types";
import {
  dispatchSourceStreamFocus,
  dispatchSourceTrace,
  resolveFocusedStreamId,
  subscribeSourceStreamFocus,
  subscribeSourceTrace
} from "./sourceSignals";

const payload = {
  streams: [
    {
      stream_id: "stream:source-gmail:inbox",
      source_id: "source-gmail",
      recipe_stream_id: "inbox",
      label: "Inbox",
      selected: true,
      privacy: "private_self",
      cadence_days: 7,
      cursor_age_days: 2,
      freshness_state: "fresh",
      breached: false,
      target_page_ids: [],
      filter_keys: [],
      skip_reason_code: ""
    }
  ]
} as unknown as SourceFoundationPayload;

describe("source stream focus signal", () => {
  it("round-trips the detail and stops after unsubscribe", () => {
    const seen = vi.fn();
    const unsubscribe = subscribeSourceStreamFocus(seen);
    dispatchSourceStreamFocus({ sourceId: "source-gmail", streamId: "stream:source-gmail:inbox" });
    expect(seen).toHaveBeenCalledWith({ sourceId: "source-gmail", streamId: "stream:source-gmail:inbox" });
    unsubscribe();
    dispatchSourceStreamFocus({ sourceId: "source-gmail", streamId: null });
    expect(seen).toHaveBeenCalledTimes(1);
  });
});

describe("source trace signal", () => {
  it("delivers trace subjects and normalizes clears to null", () => {
    const seen = vi.fn();
    const unsubscribe = subscribeSourceTrace(seen);
    dispatchSourceTrace({ mode: "downstream", subjectId: "source-gmail" });
    expect(seen).toHaveBeenLastCalledWith({ mode: "downstream", subjectId: "source-gmail" });
    dispatchSourceTrace(null);
    expect(seen).toHaveBeenLastCalledWith(null);
    unsubscribe();
    dispatchSourceTrace({ mode: "closure", subjectId: "x" });
    expect(seen).toHaveBeenCalledTimes(2);
  });
});

describe("resolveFocusedStreamId (§12.3)", () => {
  it("maps a derived stream id to the dock's recipe stream id", () => {
    expect(
      resolveFocusedStreamId(payload, { sourceId: "source-gmail", streamId: "stream:source-gmail:inbox" })
    ).toBe("inbox");
  });

  it("returns null for overflow ports, foreign sources and missing payloads", () => {
    expect(resolveFocusedStreamId(payload, { sourceId: "source-gmail", streamId: null })).toBeNull();
    expect(
      resolveFocusedStreamId(payload, { sourceId: "source-other", streamId: "stream:source-gmail:inbox" })
    ).toBeNull();
    expect(
      resolveFocusedStreamId(undefined, { sourceId: "source-gmail", streamId: "stream:source-gmail:inbox" })
    ).toBeNull();
    expect(resolveFocusedStreamId(payload, null)).toBeNull();
  });
});
