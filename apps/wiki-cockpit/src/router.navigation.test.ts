// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { getRouteUrlSnapshot, navigate, subscribeRouteUrl } from "./router";

afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
});

describe("router history subscription", () => {
  it("publishes programmatic route writes through a browser-wide event", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeRouteUrl(listener);

    navigate("/demo/w?center=root&view=quadrants&lens=all&overlay=actions");

    expect(getRouteUrlSnapshot()).toBe("/demo/w?center=root&view=quadrants&lens=all&overlay=actions");
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    navigate("/");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
