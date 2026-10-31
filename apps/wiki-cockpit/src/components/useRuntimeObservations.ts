import { useCallback, useEffect, useRef, useState } from "react";
import type { RuntimeObservationReader, RuntimeObservations } from "../data/runtimeObservations";

export function useRuntimeObservations(read?: RuntimeObservationReader, disabled = false) {
  const [observation, setObservation] = useState<RuntimeObservations | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const generation = useRef(0);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!read || disabled) return;
    const request = ++generation.current;
    try {
      const value = await read({ signal });
      if (!signal?.aborted && request === generation.current) { setObservation(value); setUnavailable(false); }
    } catch { if (!signal?.aborted && request === generation.current) setUnavailable(true); }
  }, [read, disabled]);
  useEffect(() => {
    setObservation(null); setUnavailable(false);
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => { generation.current++; controller.abort(); };
  }, [refresh]);
  return { observation, unavailable, refresh };
}
