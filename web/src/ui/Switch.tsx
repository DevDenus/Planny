import { cx } from "./cx";
import styles from "./Switch.module.css";

export type SwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  className?: string;
};

export function Switch({ checked, onChange, label, disabled, className }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(styles.switch, className)}
    >
      <span aria-hidden="true" className={styles.track}>
        <span className={styles.thumb} />
      </span>
      <span className={styles.label}>{label}</span>
    </button>
  );
}
