import { useEffect, useRef } from "react";

/** Puts the focus on the first field that the last check refused. The ref goes on the form. */
export function useFocusInvalid<Area extends HTMLElement = HTMLFormElement>(errors: unknown) {
  const area = useRef<Area>(null);
  useEffect(() => {
    area.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [errors]);
  return area;
}
