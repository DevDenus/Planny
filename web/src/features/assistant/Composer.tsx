import { Mic, SendHorizontal } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";

import { Button, IconButton, Spinner, TextArea } from "../../ui";
import styles from "./Composer.module.css";
import { useVoiceInput } from "./useVoiceInput";

export const MESSAGE_MAX_LENGTH = 2000;

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export type ComposerProps = {
  text: string;
  onText: (text: string) => void;
  onSend: () => void;
  /** The assistant is answering or the chat is closed. */
  disabled: boolean;
  hint?: string;
  error?: string;
  voice: boolean;
};

export function Composer({ text, onText, onSend, disabled, hint, error, voice }: ComposerProps) {
  const field = useRef<HTMLTextAreaElement>(null);
  const textRef = useRef(text);
  useEffect(() => {
    textRef.current = text;
  }, [text]);

  const recorder = useVoiceInput((heard) => {
    const current = textRef.current;
    onText(current ? `${current} ${heard}` : heard);
    // The field is disabled until the recognition ends, so it takes focus a moment later.
    window.setTimeout(() => field.current?.focus());
  });
  const busy = recorder.state !== "idle";

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (text.trim() && !disabled && !busy) onSend();
  };

  return (
    <div className={styles.composer}>
      {hint && <p className={styles.hint}>{hint}</p>}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {recorder.error && (
        <p className={styles.error} role="alert">
          {recorder.error}
        </p>
      )}
      {recorder.state === "recording" ? (
        <div className={styles.recording} role="status">
          <span className={styles.dot} aria-hidden="true" />
          <span>Запись {clock(recorder.seconds)}</span>
          <div className={styles.recordingActions}>
            <Button variant="secondary" onClick={recorder.cancel}>
              Отмена
            </Button>
            <Button onClick={recorder.stop}>Готово</Button>
          </div>
        </div>
      ) : (
        <div className={styles.row}>
          <div className={styles.field}>
            <TextArea
              ref={field}
              label="Сообщение"
              hideLabel
              rows={2}
              maxLength={MESSAGE_MAX_LENGTH}
              value={text}
              disabled={disabled || recorder.state === "transcribing"}
              onChange={(event) => onText(event.target.value)}
              onKeyDown={onKeyDown}
            />
            {recorder.state === "transcribing" && (
              <p className={styles.transcribing} role="status">
                <Spinner size={14} /> Распознаю…
              </p>
            )}
          </div>
          {voice && (
            <IconButton
              label="Записать голос"
              disabled={disabled || busy}
              onClick={() => void recorder.start()}
            >
              <Mic size={20} />
            </IconButton>
          )}
          <IconButton
            label="Отправить"
            disabled={disabled || busy || !text.trim()}
            onClick={onSend}
          >
            <SendHorizontal size={20} />
          </IconButton>
        </div>
      )}
    </div>
  );
}
