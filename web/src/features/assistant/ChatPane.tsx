import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, type AssistantCard } from "../../api/client";
import { Banner, EmptyState, LoadError, Skeleton } from "../../ui";
import { failureMessage } from "../tasks/api";
import { useChat, useCreateChat, useSendMessage } from "./api";
import { CardPanel } from "./CardPanel";
import styles from "./ChatPane.module.css";
import { Composer } from "./Composer";

function sendError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Ассистент ещё отвечает";
    if (error.status === 503) return "Ассистент сейчас недоступен";
    if (error.status === 409) return "Чат закрыт: карточка удалена";
  }
  return failureMessage(error);
}

export type ChatPaneProps = {
  /** Without an id the pane is a new chat, which starts with the first message. */
  chatId?: string;
  voice: boolean;
};

export function ChatPane({ chatId, voice }: ChatPaneProps) {
  const navigate = useNavigate();
  const chatQuery = useChat(chatId);
  const chat = chatQuery.data;
  const create = useCreateChat();
  const send = useSendMessage(chatId ?? "");
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const draftRef = useRef<AssistantCard | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const lastId = chat?.messages.at(-1)?.id;
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lastId, pending]);

  const submit = async () => {
    const value = text.trim();
    if (!value || pending !== null) return;
    setError(undefined);
    setText("");
    setPending(value);
    try {
      if (chat === undefined) {
        const created = await create.mutateAsync(value);
        setPending(null);
        void navigate(`/assistant/${created.id}`, { replace: true });
        return;
      }
      // The card goes only while it is a draft: later the server reads the task or event itself.
      const card = chat.state === "draft" ? draftRef.current : null;
      await send.mutateAsync({ text: value, card });
    } catch (failure) {
      setText(value);
      setError(sendError(failure));
    }
    setPending(null);
  };

  if (chatId !== undefined && chat === undefined) {
    if (chatQuery.isPending) return <Skeleton height={240} />;
    if (chatQuery.error instanceof ApiError && chatQuery.error.status === 404) {
      return (
        <EmptyState title="Чат не найден" action={<Link to="/assistant">Начать новый</Link>} />
      );
    }
    return (
      <LoadError
        message={failureMessage(chatQuery.error)}
        onRetry={() => void chatQuery.refetch()}
      />
    );
  }

  const closed = chat?.state === "deleted";
  const card = chat?.card;

  return (
    <div className={styles.pane}>
      <div className={styles.thread}>
        {chat === undefined && pending === null && (
          <p className={styles.intro}>
            Опишите задачу или событие своими словами, например: «Завтра в 19:00 ужин с Машей».
            Ассистент заполнит карточку, а вы проверите её и создадите.
          </p>
        )}
        <ul className={styles.messages}>
          {chat?.messages.map((message) => (
            <li
              key={message.id}
              className={message.role === "user" ? styles.user : styles.assistant}
            >
              <p className={styles.text}>{message.text}</p>
              {message.warnings.length > 0 && (
                <ul className={styles.warnings}>
                  {message.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {pending !== null && (
            <>
              <li className={styles.user}>
                <p className={styles.text}>{pending}</p>
              </li>
              <li className={styles.assistant} role="status">
                <p className={styles.text}>Думаю…</p>
              </li>
            </>
          )}
        </ul>
        {chat && closed && <Banner tone="info">Карточка удалена</Banner>}
        {chat && !closed && card && (
          <CardPanel
            // A new answer brings a new proposal, so the form starts again from it.
            key={`${chat.id}:${lastId}`}
            chatId={chat.id}
            created={chat.state === "created"}
            card={card}
            draftRef={draftRef}
          />
        )}
        <div ref={end} />
      </div>
      <Composer
        text={text}
        onText={setText}
        onSend={() => void submit()}
        disabled={pending !== null || closed}
        hint={closed ? "Чат закрыт: карточка удалена" : undefined}
        error={error}
        voice={voice}
      />
    </div>
  );
}
