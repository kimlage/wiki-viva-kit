// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSurfacePresence } from "./useSurfacePresence";

function Surface({ open }: { open: boolean }) {
  const presence = useSurfacePresence(open, 320);
  if (!presence.mounted) return null;
  return (
    <div
      data-testid="surface"
      data-phase={presence.phase}
      onAnimationEnd={(event) => {
        if (event.currentTarget === event.target) presence.completeExit();
      }}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useSurfacePresence", () => {
  it("keeps a closing surface mounted until its semantic exit completes", () => {
    vi.useFakeTimers();
    const { getByTestId, queryByTestId, rerender } = render(<Surface open />);

    rerender(<Surface open={false} />);
    expect(getByTestId("surface").dataset.phase).toBe("closing");
    act(() => vi.advanceTimersByTime(319));
    expect(queryByTestId("surface")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1));
    expect(queryByTestId("surface")).toBeNull();
  });

  it("cancels an exit when the same surface reopens", () => {
    vi.useFakeTimers();
    const { getByTestId, rerender } = render(<Surface open />);

    rerender(<Surface open={false} />);
    expect(getByTestId("surface").dataset.phase).toBe("closing");
    rerender(<Surface open />);
    expect(getByTestId("surface").dataset.phase).toBe("open");
    act(() => vi.advanceTimersByTime(400));
    expect(getByTestId("surface").dataset.phase).toBe("open");
  });
});
