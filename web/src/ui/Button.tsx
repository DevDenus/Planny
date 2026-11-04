import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "./cx";
import { Spinner } from "./Spinner";
import styles from "./Button.module.css";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "lg";
  fullWidth?: boolean;
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  fullWidth = false,
  loading = false,
  icon,
  type = "button",
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  const leading = loading ? (
    <Spinner size={size === "lg" ? 18 : 16} />
  ) : icon ? (
    <span className={styles.icon}>{icon}</span>
  ) : null;

  return (
    <button
      {...rest}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        styles.button,
        styles[variant],
        styles[size],
        fullWidth && styles.fullWidth,
        className,
      )}
    >
      {leading}
      {children}
    </button>
  );
}
