import type { HTMLAttributes } from "react";

import { cx } from "./cx";
import styles from "./Panel.module.css";

export type PanelProps = HTMLAttributes<HTMLDivElement>;

export function Panel({ className, ...rest }: PanelProps) {
  return <div {...rest} className={cx(styles.panel, className)} />;
}
