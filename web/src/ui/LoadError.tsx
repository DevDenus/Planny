import { Banner } from "./Banner";
import { Button } from "./Button";
import styles from "./LoadError.module.css";

export type LoadErrorProps = {
  message?: string;
  onRetry: () => void;
};

export function LoadError({ message = "Не удалось загрузить данные", onRetry }: LoadErrorProps) {
  return (
    <div className={styles.loadError}>
      <Banner tone="error">{message}</Banner>
      <Button variant="secondary" onClick={onRetry}>
        Повторить
      </Button>
    </div>
  );
}
