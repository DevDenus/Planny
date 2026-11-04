import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "./cx";
import styles from "./Banner.module.css";

export type BannerProps = {
  tone: "info" | "success" | "warning" | "error";
  children: ReactNode;
};

const ICONS = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  error: CircleAlert,
} as const;

export function Banner({ tone, children }: BannerProps) {
  const Icon = ICONS[tone];

  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx(styles.banner, styles[tone])}>
      <Icon size={20} className={styles.icon} />
      <div className={styles.text}>{children}</div>
    </div>
  );
}
