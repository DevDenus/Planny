import type { ButtonHTMLAttributes } from "react";

import { cx } from "./cx";
import styles from "./IconButton.module.css";

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  badge?: number;
};

export function IconButton({
  label,
  badge,
  type = "button",
  className,
  children,
  ...rest
}: IconButtonProps) {
  const count = badge ?? 0;

  return (
    <button
      {...rest}
      type={type}
      aria-label={label}
      title={label}
      className={cx(styles.iconButton, className)}
    >
      {children}
      {count > 0 && <span className={styles.badge}>{count > 99 ? "99+" : count}</span>}
    </button>
  );
}
