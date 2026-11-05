import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router";
import { User } from "lucide-react";

import { ApiError } from "../../api/client";
import { Banner, Button, PasswordField, TextField } from "../../ui";
import { AuthLayout } from "./AuthLayout";
import styles from "./AuthLayout.module.css";
import { useLogin, useSession } from "./session";

export type LoginState = { from: string; expired: boolean };

export function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "rate_limited") {
    const seconds = Number(error.details.retry_after ?? 60);
    return `Слишком много попыток. Повторите через ${Math.ceil(seconds / 60)} мин`;
  }
  return error instanceof ApiError ? error.message : "Не удалось войти. Попробуйте ещё раз";
}

export function LoginPage() {
  const location = useLocation();
  const state = location.state as LoginState | null;
  const { user } = useSession();
  const { mutate, error, isPending } = useLogin();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");

  // The only way out of this page: a successful login reloads the user, which lands here.
  if (user) {
    return <Navigate to={state?.from ?? "/"} replace />;
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutate({ login, password });
  };

  return (
    <AuthLayout title="Вход" footer="Забыли пароль? Обратитесь к администратору">
      <form className={styles.form} onSubmit={submit}>
        <TextField
          label="Логин"
          hideLabel
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
          autoFocus
          icon={<User size={18} />}
          value={login}
          onChange={(event) => setLogin(event.target.value)}
        />
        <PasswordField
          label="Пароль"
          hideLabel
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {state?.expired && !error && <Banner tone="info">Сеанс завершён, войдите снова</Banner>}
        {error && <Banner tone="error">{loginErrorMessage(error)}</Banner>}
        <Button type="submit" size="lg" fullWidth loading={isPending}>
          Войти
        </Button>
      </form>
    </AuthLayout>
  );
}
