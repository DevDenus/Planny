import { useId } from "react";
import type { InputHTMLAttributes, ReactNode, Ref } from "react";

import { cx } from "./cx";
import styles from "./TextField.module.css";

export type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  /** Short forms: the label moves into the placeholder and stays for screen readers. */
  hideLabel?: boolean;
  error?: string;
  hint?: string;
  icon?: ReactNode;
  trailing?: ReactNode;
  ref?: Ref<HTMLInputElement>;
};

export function TextField({
  label,
  hideLabel,
  error,
  hint,
  icon,
  trailing,
  id,
  className,
  ref,
  placeholder,
  "aria-describedby": describedBy,
  ...rest
}: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const messageId = `${inputId}-message`;
  const message = error || hint;
  const ariaDescribedBy =
    [describedBy, message ? messageId : undefined].filter(Boolean).join(" ") || undefined;

  return (
    <div className={styles.field}>
      <label htmlFor={inputId} className={hideLabel ? styles.labelHidden : styles.label}>
        {label}
      </label>
      <div className={styles.control}>
        {icon ? <span className={styles.icon}>{icon}</span> : null}
        <input
          {...rest}
          ref={ref}
          id={inputId}
          placeholder={placeholder ?? (hideLabel ? label : undefined)}
          className={cx(
            styles.input,
            Boolean(icon) && styles.hasIcon,
            Boolean(trailing) && styles.hasTrailing,
            Boolean(error) && styles.invalid,
            className,
          )}
          aria-invalid={error ? true : undefined}
          aria-describedby={ariaDescribedBy}
        />
        {trailing ? <span className={styles.trailing}>{trailing}</span> : null}
      </div>
      {message ? (
        <p id={messageId} className={error ? styles.error : styles.hint}>
          {message}
        </p>
      ) : null}
    </div>
  );
}
