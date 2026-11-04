import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { Banner, Button, PasswordField } from "../../ui";
import { AuthLayout } from "./AuthLayout";
import styles from "./AuthLayout.module.css";
import { PASSWORD_MIN_LENGTH, validateNewPassword, type NewPasswordErrors } from "./password";
import { useChangePassword } from "./session";

/** Opens by itself after a first login or a reset, and can't be skipped. */
export function ChangePasswordPage() {
  const navigate = useNavigate();
  const { mutate, isPending, error } = useChangePassword();
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [errors, setErrors] = useState<NewPasswordErrors>({});
  const passwordRef = useRef<HTMLInputElement>(null);
  const repeatRef = useRef<HTMLInputElement>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = validateNewPassword(password, repeat);
    setErrors(found);
    if (found.password) {
      passwordRef.current?.focus();
      return;
    }
    if (found.repeat) {
      repeatRef.current?.focus();
      return;
    }
    mutate({ new_password: password }, { onSuccess: () => navigate("/", { replace: true }) });
  };

  const serverField = error instanceof ApiError ? error.fields.new_password : undefined;

  return (
    <AuthLayout title="Смена пароля" subtitle="Для продолжения работы установите новый пароль.">
      <form className={styles.form} onSubmit={submit} noValidate>
        <PasswordField
          ref={passwordRef}
          label="Новый пароль"
          hideLabel
          name="new-password"
          autoComplete="new-password"
          autoFocus
          value={password}
          error={errors.password ?? serverField}
          onChange={(event) => setPassword(event.target.value)}
        />
        <PasswordField
          ref={repeatRef}
          label="Повторите пароль"
          hideLabel
          name="repeat-password"
          autoComplete="new-password"
          value={repeat}
          error={errors.repeat}
          onChange={(event) => setRepeat(event.target.value)}
        />
        <Banner tone="info">
          Пароль должен содержать не менее {PASSWORD_MIN_LENGTH} символов.
        </Banner>
        {error && !serverField && (
          <Banner tone="error">
            {error instanceof ApiError ? error.message : "Не удалось сохранить пароль"}
          </Banner>
        )}
        <Button type="submit" size="lg" fullWidth loading={isPending}>
          Сохранить пароль
        </Button>
      </form>
    </AuthLayout>
  );
}
