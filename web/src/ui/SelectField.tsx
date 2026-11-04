import { useId } from "react";
import type { Ref, SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";

import { cx } from "./cx";
import styles from "./SelectField.module.css";

/* A native select on purpose: phones show their system picker for it. */
export type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> & {
  label: string;
  /** Short forms: the label stays for screen readers only. */
  hideLabel?: boolean;
  error?: string;
  hint?: string;
  options: { value: string; label: string }[];
  ref?: Ref<HTMLSelectElement>;
};

export function SelectField({
  label,
  hideLabel,
  error,
  hint,
  options,
  id,
  className,
  ref,
  "aria-describedby": describedBy,
  ...rest
}: SelectFieldProps) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const messageId = `${selectId}-message`;
  const message = error || hint;
  const ariaDescribedBy =
    [describedBy, message ? messageId : undefined].filter(Boolean).join(" ") || undefined;

  return (
    <div className={styles.field}>
      <label htmlFor={selectId} className={hideLabel ? styles.labelHidden : styles.label}>
        {label}
      </label>
      <div className={styles.control}>
        <select
          {...rest}
          ref={ref}
          id={selectId}
          className={cx(styles.select, Boolean(error) && styles.invalid, className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={ariaDescribedBy}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown size={20} aria-hidden="true" className={styles.icon} />
      </div>
      {message ? (
        <p id={messageId} className={error ? styles.error : styles.hint}>
          {message}
        </p>
      ) : null}
    </div>
  );
}
