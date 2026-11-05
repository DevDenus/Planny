import { Component, type ReactNode } from "react";

import styles from "./ErrorBoundary.module.css";
import { LoadError } from "./LoadError";

type ErrorBoundaryProps = { children: ReactNode };

/** The last line of defence: a failed render otherwise leaves a blank page with no way out. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className={styles.errorBoundary}>
        <LoadError
          message="Что-то пошло не так. Попробуйте загрузить страницу ещё раз"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }
}
