import { useState } from "react";
import { Eye, EyeOff, Lock } from "lucide-react";

import { IconButton } from "./IconButton";
import { TextField } from "./TextField";
import type { TextFieldProps } from "./TextField";

export type PasswordFieldProps = Omit<TextFieldProps, "type" | "icon" | "trailing">;

export function PasswordField(props: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <TextField
      {...props}
      type={visible ? "text" : "password"}
      icon={<Lock size={18} />}
      trailing={
        <IconButton
          type="button"
          label={visible ? "Скрыть пароль" : "Показать пароль"}
          disabled={props.disabled}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeOff size={20} /> : <Eye size={20} />}
        </IconButton>
      }
    />
  );
}
