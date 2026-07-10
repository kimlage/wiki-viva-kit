import { useCallback, useEffect, useState } from "react";

export type SurfacePhase = "open" | "closing";

/**
 * Keeps a surface mounted long enough to tell the closing half of its story.
 * The visual duration remains a CSS token; the timeout is only a defensive
 * cleanup for browsers that suppress animation events in background tabs.
 */
export function useSurfacePresence(open: boolean, fallbackExitMs = 1600) {
  const [mounted, setMounted] = useState(open);
  const [phase, setPhase] = useState<SurfacePhase>("open");

  const completeExit = useCallback(() => {
    setMounted(false);
    setPhase("open");
  }, []);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setPhase("open");
    } else if (mounted) {
      setPhase("closing");
    }
  }, [mounted, open]);

  useEffect(() => {
    if (phase !== "closing") return undefined;
    const timeout = window.setTimeout(completeExit, fallbackExitMs);
    return () => window.clearTimeout(timeout);
  }, [completeExit, fallbackExitMs, phase]);

  return { mounted, phase, completeExit };
}
