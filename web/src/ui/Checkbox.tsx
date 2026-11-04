import { Check } from "lucide-react";

import { cx } from "./cx";
import styles from "./Checkbox.module.css";

export type CheckboxProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hideLabel?: boolean;
  disabled?: boolean;
  className?: string;
};

export function Checkbox({
  checked,
  onChange,
  label,
  hideLabel,
  disabled,
  className,
}: CheckboxProps) {
  return (
    <label
      className={cx(
        styles.checkbox,
        hideLabel && styles.compact,
        disabled && styles.disabled,
        className,
      )}
    >
      <input
        type="checkbox"
        className={styles.input}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span aria-hidden="true" className={styles.box}>
        {checked ? <Check size={16} /> : null}
      </span>
      <span className={hideLabel ? styles.labelHidden : styles.label}>{label}</span>
    </label>
  );
}
