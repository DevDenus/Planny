import { cx } from "./cx";
import styles from "./SegmentedControl.module.css";

export type SegmentedControlProps<T extends string> = {
  label: string;
  value: T;
  options: { value: T; label: string; disabled?: boolean; title?: string }[];
  onChange: (value: T) => void;
  className?: string;
};

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div role="radiogroup" aria-label={label} className={cx(styles.group, className)}>
      {options.map((option) => {
        const selected = option.value === value;

        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            title={option.title}
            onClick={() => {
              if (!selected) {
                onChange(option.value);
              }
            }}
            className={cx(styles.segment, selected && styles.selected)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
