import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { IconButton } from "./IconButton";
import styles from "./Dialog.module.css";

export type DialogProps = {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
};

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/* A conflict dialog opens over a form. Esc must close only the top one, or the form is lost. */
const openDialogs: object[] = [];

/* Mounted only while open, so the parent controls when it appears and disappears. */
export function Dialog({ title, onClose, children, footer, width = 560 }: DialogProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const pressStartedOnOverlay = useRef(false);
  const self = useRef({});

  useEffect(() => {
    const entry = self.current;
    openDialogs.push(entry);
    const opener = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();

    return () => {
      openDialogs.splice(openDialogs.indexOf(entry), 1);
      document.body.style.overflow = previousOverflow;
      if (opener instanceof HTMLElement) {
        opener.focus();
      }
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (openDialogs.at(-1) !== self.current) {
        return;
      }

      if (event.key === "Escape") {
        onClose();
        return;
      }

      const panel = panelRef.current;
      if (event.key !== "Tab" || !panel) {
        return;
      }

      const focusable = panel.querySelectorAll<HTMLElement>(FOCUSABLE);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) {
        event.preventDefault();
        panel.focus();
        return;
      }

      // The panel itself can hold focus right after opening, so it counts as the start.
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || active === panel || !panel.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !panel.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      className={styles.overlay}
      onPointerDown={(event) => {
        pressStartedOnOverlay.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        // Browsers send a click to the nearest common ancestor, so a drag that starts
        // in the panel and ends on the overlay would otherwise close the dialog.
        if (pressStartedOnOverlay.current && event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={styles.panel}
        style={{ width }}
      >
        <div className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
          <IconButton label="Закрыть" className={styles.close} onClick={onClose}>
            <X size={20} />
          </IconButton>
        </div>
        <div className={styles.body}>{children}</div>
        {footer ? <div className={styles.footer}>{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
