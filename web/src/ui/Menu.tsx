import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";

import { cx } from "./cx";
import { IconButton } from "./IconButton";
import styles from "./Menu.module.css";

export type MenuItem = {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  /** Explains a disabled item: shown as a second line under the label. */
  hint?: string;
  danger?: boolean;
};

export type MenuProps = { label: string; items: MenuItem[]; className?: string };

/** Space between the trigger and the list, and the least space kept from a viewport edge. */
const GAP = 4;
const EDGE = 8;

const ITEM = '[role="menuitem"]';
const ENABLED_ITEM = '[role="menuitem"]:not([aria-disabled="true"])';

/**
 * CSS variables that place the list: under the trigger unless it would not fit there, then above
 * it, and right-aligned to the trigger unless that would push it off the left edge.
 */
function placeList(anchor: DOMRect, width: number, height: number): Record<string, string> {
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;
  const fitsBelow = anchor.bottom + GAP + height <= viewportHeight - EDGE;
  const fitsAbove = anchor.top - GAP - height >= EDGE;
  const vars: Record<string, string> = {};

  if (fitsBelow || !fitsAbove) {
    vars["--menu-top"] = `${anchor.bottom + GAP}px`;
  } else {
    vars["--menu-bottom"] = `${viewportHeight - anchor.top + GAP}px`;
  }
  if (anchor.right - width >= EDGE) {
    vars["--menu-right"] = `${viewportWidth - anchor.right}px`;
  } else {
    vars["--menu-left"] = `${EDGE}px`;
  }
  return vars;
}

function isWithin(target: EventTarget | null, element: HTMLElement | null): boolean {
  return target instanceof Node && element !== null && element.contains(target);
}

/* A press or click on the menu must not reach a parent, such as a draggable card or a row that opens on click. */
function stopPropagation(event: SyntheticEvent) {
  event.stopPropagation();
}

export function Menu({ label, items, className }: MenuProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  /* Focus goes back to the trigger, except when the user pressed somewhere else: that press moves focus itself. */
  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) {
      triggerRef.current?.focus({ preventScroll: true });
    }
  }, []);

  /* Runs before paint, so the list is placed and focused without a visible jump. */
  useLayoutEffect(() => {
    const list = listRef.current;
    const trigger = triggerRef.current;
    if (!open || !list || !trigger) return;

    const vars = placeList(trigger.getBoundingClientRect(), list.offsetWidth, list.offsetHeight);
    for (const [name, value] of Object.entries(vars)) {
      list.style.setProperty(name, value);
    }
    list.querySelector<HTMLElement>(ENABLED_ITEM)?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      if (isWithin(event.target, listRef.current) || isWithin(event.target, triggerRef.current)) {
        return;
      }
      close(false);
    }

    // The list may scroll itself on a phone, which is not a reason to close it.
    function handleViewportChange(event: Event) {
      if (!isWithin(event.target, listRef.current)) {
        close(true);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("scroll", handleViewportChange, true);
    window.addEventListener("resize", handleViewportChange);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("scroll", handleViewportChange, true);
      window.removeEventListener("resize", handleViewportChange);
    };
  }, [open, close]);

  function handleListKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    // Tab closes the list and goes on from the trigger, so a dialog around the card still traps focus.
    if (event.key === "Tab") {
      close(true);
      return;
    }
    event.stopPropagation();

    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(ITEM));
    const current = buttons.findIndex((button) => button === document.activeElement);
    const last = buttons.length - 1;
    let next: number;

    switch (event.key) {
      case "ArrowDown":
        next = current < last ? current + 1 : 0;
        break;
      case "ArrowUp":
        next = current > 0 ? current - 1 : last;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = last;
        break;
      case "Escape":
        event.preventDefault();
        close(true);
        return;
      default:
        return;
    }
    event.preventDefault();
    buttons[next]?.focus({ preventScroll: true });
  }

  function choose(item: MenuItem) {
    if (item.disabled) return;
    // Focus is back on the trigger before onSelect runs, so a dialog it opens returns focus there.
    close(true);
    item.onSelect();
  }

  return (
    <>
      <IconButton
        label={label}
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        onPointerDown={stopPropagation}
        onMouseDown={stopPropagation}
        onTouchStart={stopPropagation}
        onKeyDown={(event) => {
          // Escape and Tab go on to a dialog around the card: it closes on the one and traps the other.
          if (event.key !== "Escape" && event.key !== "Tab") event.stopPropagation();
        }}
        onClick={(event) => {
          event.stopPropagation();
          if (open) {
            close(true);
            return;
          }
          triggerRef.current = event.currentTarget;
          setOpen(true);
        }}
      >
        <MoreHorizontal size={18} />
      </IconButton>
      {open
        ? createPortal(
            <div
              ref={listRef}
              role="menu"
              aria-label={label}
              className={styles.menu}
              onKeyDown={handleListKeyDown}
              onPointerDown={stopPropagation}
              onMouseDown={stopPropagation}
              onTouchStart={stopPropagation}
              onClick={stopPropagation}
            >
              {items.map((item, index) => {
                const labelId = `${id}-label-${index}`;
                const hintId = `${id}-hint-${index}`;
                return (
                  <button
                    key={index}
                    type="button"
                    role="menuitem"
                    aria-disabled={item.disabled ? "true" : undefined}
                    aria-labelledby={labelId}
                    aria-describedby={item.hint ? hintId : undefined}
                    className={cx(styles.item, item.danger && styles.danger)}
                    onClick={() => choose(item)}
                  >
                    <span id={labelId}>{item.label}</span>
                    {item.hint ? (
                      <span id={hintId} className={styles.hint}>
                        {item.hint}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
