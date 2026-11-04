import { CalendarCheck } from "lucide-react";

import { cx } from "./cx";
import styles from "./Logo.module.css";

export type LogoProps = {
  size?: "md" | "lg";
  wordmark?: boolean;
};

export function Logo({ size = "md", wordmark = true }: LogoProps) {
  const iconSize = size === "lg" ? 40 : 24;

  if (!wordmark) {
    return <CalendarCheck role="img" aria-label="Planny" size={iconSize} className={styles.icon} />;
  }

  return (
    <span className={cx(styles.logo, styles[size])}>
      <CalendarCheck size={iconSize} className={styles.icon} aria-hidden="true" />
      <span className={styles.wordmark}>Planny</span>
    </span>
  );
}
