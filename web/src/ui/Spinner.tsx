import styles from "./Spinner.module.css";

export type SpinnerProps = {
  size?: number;
};

export function Spinner({ size = 16 }: SpinnerProps) {
  return (
    <span aria-hidden="true" className={styles.spinner} style={{ width: size, height: size }} />
  );
}
