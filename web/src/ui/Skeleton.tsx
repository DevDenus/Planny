import styles from "./Skeleton.module.css";

export type SkeletonProps = {
  width?: number | string;
  height?: number | string;
  radius?: string;
};

/* Undefined values are left out of the style, so the CSS defaults apply. */
export function Skeleton({ width, height, radius }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      className={styles.skeleton}
      style={{ width, height, borderRadius: radius }}
    />
  );
}
