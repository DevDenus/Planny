import { useId } from "react";
import type { Ref, TextareaHTMLAttributes } from "react";

import { cx } from "./cx";
import styles from "./TextArea.module.css";

export type TextAreaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: string;
  /** Short forms: the label moves into the placeholder and stays for screen readers. */
  hideLabel?: boolean;
  error?: string;
  hint?: string;
  ref?: Ref<HTMLTextAreaElement>;
};

export function TextArea({
  label,
  hideLabel,
  error,
  hint,
  id,
  className,
  ref,
  placeholder,
  "aria-describedby": describedBy,
  ...rest
}: TextAreaProps) {
  const generatedId = useId();
  const textareaId = id ?? generatedId;
  const messageId = `${textareaId}-message`;
  const message = error || hint;
  const ariaDescribedBy =
    [describedBy, message ? messageId : undefined].filter(Boolean).join(" ") || undefined;

  return (
    <div className={styles.field}>
      <label htmlFor={textareaId} className={hideLabel ? styles.labelHidden : styles.label}>
        {label}
      </label>
      <textarea
        {...rest}
        ref={ref}
        id={textareaId}
        placeholder={placeholder ?? (hideLabel ? label : undefined)}
        className={cx(styles.textarea, Boolean(error) && styles.invalid, className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={ariaDescribedBy}
      />
      {message ? (
        <p id={messageId} className={error ? styles.error : styles.hint}>
          {message}
        </p>
      ) : null}
    </div>
  );
}
