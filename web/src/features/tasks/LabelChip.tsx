import type { Label } from "../../api/client";
import { cx } from "../../ui";
import styles from "./LabelChip.module.css";

/** A label as a small pill. Its colours come from the palette tokens, so a theme can change them. */
export function LabelChip({
  label,
  className,
}: {
  label: Pick<Label, "name" | "color">;
  className?: string;
}) {
  return (
    <span
      className={cx(styles.chip, className)}
      style={{
        background: `var(--cat-${label.color}-fill)`,
        color: `var(--cat-${label.color})`,
      }}
      title={label.name}
    >
      {label.name}
    </span>
  );
}
