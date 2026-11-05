import { LogOut } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { Banner, Button, Panel, PasswordField } from "../../ui";
import { PASSWORD_MIN_LENGTH, validateNewPassword, type NewPasswordErrors } from "../auth/password";
import { useChangePassword, useLogout } from "../auth/session";
import { CategoriesSection } from "./CategoriesSection";
import styles from "./SettingsPage.module.css";

function PasswordSection() {
  const { mutate, isPending, isSuccess, error, reset } = useChangePassword();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [errors, setErrors] = useState<NewPasswordErrors>({});
  const passwordRef = useRef<HTMLInputElement>(null);
  const repeatRef = useRef<HTMLInputElement>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    reset();
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
    mutate(
      { current_password: current, new_password: password },
      {
        onSuccess: () => {
          setCurrent("");
          setPassword("");
          setRepeat("");
        },
      },
    );
  };

  const fields = error instanceof ApiError ? error.fields : {};
  const hasFieldError = Boolean(fields.current_password ?? fields.new_password);

  return (
    <Panel className={styles.section}>
      <h2 className={styles.heading}>Пароль</h2>
      <form className={styles.form} onSubmit={submit} noValidate>
        <PasswordField
          label="Текущий пароль"
          name="current-password"
          autoComplete="current-password"
          value={current}
          error={fields.current_password}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <PasswordField
          ref={passwordRef}
          label="Новый пароль"
          name="new-password"
          autoComplete="new-password"
          hint={`Не менее ${PASSWORD_MIN_LENGTH} символов`}
          value={password}
          error={errors.password ?? fields.new_password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <PasswordField
          ref={repeatRef}
          label="Повторите пароль"
          name="repeat-password"
          autoComplete="new-password"
          value={repeat}
          error={errors.repeat}
          onChange={(event) => setRepeat(event.target.value)}
        />
        {isSuccess && <Banner tone="success">Пароль изменён, другие сеансы закрыты</Banner>}
        {error && !hasFieldError && (
          <Banner tone="error">
            {error instanceof ApiError ? error.message : "Не удалось сохранить пароль"}
          </Banner>
        )}
        <div>
          <Button type="submit" loading={isPending}>
            Сохранить пароль
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function LogoutSection() {
  const navigate = useNavigate();
  const { mutate, isPending, isError } = useLogout();

  return (
    <Panel className={styles.section}>
      <h2 className={styles.heading}>Выход</h2>
      {isError && <Banner tone="error">Не удалось выйти. Попробуйте ещё раз</Banner>}
      <div>
        <Button
          variant="danger"
          icon={<LogOut size={18} />}
          loading={isPending}
          onClick={() =>
            mutate(undefined, { onSuccess: () => navigate("/login", { replace: true }) })
          }
        >
          Выйти
        </Button>
      </div>
    </Panel>
  );
}

export function SettingsPage() {
  return (
    <section className={styles.page}>
      <h1 className={styles.title}>Настройки</h1>
      <CategoriesSection />
      <PasswordSection />
      <LogoutSection />
    </section>
  );
}
