import { useEffect, useState } from "react";

const TICK_MS = 60_000;

/**
 * The current time, refreshed every minute. Timers sleep in a background tab or on a locked
 * phone, so a visibility change refreshes it as well.
 */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const refresh = () => setNow(new Date());
    const timer = setInterval(refresh, TICK_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  return now;
}
