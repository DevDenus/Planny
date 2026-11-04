export const PASSWORD_MIN_LENGTH = 8;

export interface NewPasswordErrors {
  password?: string;
  repeat?: string;
}

export function validateNewPassword(password: string, repeat: string): NewPasswordErrors {
  const errors: NewPasswordErrors = {};
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.password = `Минимум ${PASSWORD_MIN_LENGTH} символов`;
  }
  if (repeat !== password) {
    errors.repeat = "Пароли не совпадают";
  }
  return errors;
}
