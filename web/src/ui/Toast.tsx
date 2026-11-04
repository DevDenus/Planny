import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { Button } from "./Button";
import { cx } from "./cx";
import styles from "./Toast.module.css";

type ToastTone = "info" | "error";

type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
};

type ToastApi = {
  show: (message: string, tone?: ToastTone) => void;
};

export type ToastProviderProps = {
  children: ReactNode;
};

const TOAST_DURATION_MS = 5000;
const MAX_TOASTS = 3;

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const lastId = useRef(0);

  const show = useCallback((message: string, tone: ToastTone = "info") => {
    lastId.current += 1;
    const toast: ToastItem = { id: lastId.current, message, tone };
    setToasts((current) => [...current, toast].slice(-MAX_TOASTS));
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* The region is always mounted so screen readers pick up messages added later. */}
      {createPortal(
        <div aria-live="polite" className={styles.region}>
          {toasts.map((toast) => (
            <ToastCard key={toast.id} toast={toast} onDismiss={dismiss} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return api;
}

type ToastCardProps = {
  toast: ToastItem;
  onDismiss: (id: number) => void;
};

/* Each card owns its timer, so a toast removed early also clears its timer. */
function ToastCard({ toast, onDismiss }: ToastCardProps) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(toast.id), TOAST_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [toast.id, onDismiss]);

  return (
    <div className={cx(styles.toast, toast.tone === "error" && styles.error)}>
      <span className={styles.message}>{toast.message}</span>
      <Button variant="ghost" onClick={() => onDismiss(toast.id)}>
        Скрыть
      </Button>
    </div>
  );
}
