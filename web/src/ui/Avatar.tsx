import { cx } from "./cx";
import styles from "./Avatar.module.css";

export type AvatarProps = {
  name: string;
  color: string;
  size?: number;
};

const COLORS: ReadonlySet<string> = new Set([
  "violet",
  "blue",
  "teal",
  "green",
  "yellow",
  "orange",
  "red",
  "pink",
]);

export function Avatar({ name, color, size = 32 }: AvatarProps) {
  const colorKey = COLORS.has(color) ? color : "teal";
  const letter = Array.from(name.trim())[0]?.toUpperCase() ?? "";

  return (
    <span
      className={cx(styles.avatar, styles[colorKey])}
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      title={name}
    >
      {letter}
    </span>
  );
}
