import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

export type EmptyStateProps = {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
};

export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className={styles.emptyState}>
      <p className={styles.title}>{title}</p>
      {children ? <div className={styles.description}>{children}</div> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
