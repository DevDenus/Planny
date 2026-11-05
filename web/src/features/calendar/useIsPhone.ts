import { useSyncExternalStore } from "react";

const PHONE = "(max-width: 767px)";

function subscribe(listener: () => void): () => void {
  const query = window.matchMedia?.(PHONE);
  query?.addEventListener("change", listener);
  return () => query?.removeEventListener("change", listener);
}

/** The width is the same breakpoint as in the styles of the shell. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia?.(PHONE).matches ?? false);
}
