import { CalendarDays, ListChecks, MessageSquare, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate } from "react-router";

import type { AssistantChatSummary } from "../../api/client";
import { Button, Dialog, IconButton, LoadError, Skeleton } from "../../ui";
import { failureMessage } from "../tasks/api";
import { MONTHS_SHORT } from "../tasks/dates";
import { useChats, useDeleteChat } from "./api";
import styles from "./ChatList.module.css";

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** "5 мин назад", and a date once the day is over. */
export function relativeTime(moment: string, now: Date, timeZone: string): string {
  const passed = now.getTime() - new Date(moment).getTime();
  if (passed < MINUTE_MS) return "только что";
  if (passed < HOUR_MS) return `${Math.floor(passed / MINUTE_MS)} мин назад`;
  if (passed < DAY_MS) return `${Math.floor(passed / HOUR_MS)} ч назад`;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    day: "numeric",
    month: "numeric",
  }).formatToParts(new Date(moment));
  const field = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  return `${field("day")} ${MONTHS_SHORT[field("month") - 1]}`;
}

const KIND_ICONS = { task: ListChecks, event: CalendarDays };
const STATE_BADGES = { created: "Создано", deleted: "Удалено" } as const;

export type ChatListProps = {
  timeZone: string;
  onDeleted: (id: string) => void;
  /** Used on a phone, where the list closes when a new chat is asked for. */
  onNew?: () => void;
};

export function ChatList({ timeZone, onDeleted, onNew }: ChatListProps) {
  const { data: chats, isPending, isError, refetch } = useChats();
  const navigate = useNavigate();
  const remove = useDeleteChat();
  const [removing, setRemoving] = useState<AssistantChatSummary | null>(null);
  const [failure, setFailure] = useState<string>();
  const now = new Date();

  return (
    <aside className={styles.list} aria-label="Чаты">
      <Button
        variant="secondary"
        icon={<Plus size={18} />}
        className={styles.new}
        onClick={() => {
          void navigate("/assistant");
          onNew?.();
        }}
      >
        Новый чат
      </Button>
      {isPending && <Skeleton height={64} />}
      {isError && <LoadError message="Не удалось загрузить чаты" onRetry={() => void refetch()} />}
      {failure && <p className={styles.error}>{failure}</p>}
      {chats?.length === 0 && <p className={styles.empty}>Чатов пока нет</p>}
      <ul className={styles.items}>
        {chats?.map((chat) => {
          const Icon = chat.kind ? KIND_ICONS[chat.kind] : MessageSquare;
          const badge = chat.state === "draft" ? null : STATE_BADGES[chat.state];
          return (
            <li key={chat.id} className={styles.item}>
              <NavLink
                to={`/assistant/${chat.id}`}
                className={({ isActive }) =>
                  isActive ? `${styles.link} ${styles.active}` : styles.link
                }
              >
                <Icon size={18} aria-hidden="true" className={styles.icon} />
                <span className={styles.body}>
                  <span className={styles.title}>{chat.title}</span>
                  <span className={styles.meta}>
                    {badge && <span className={styles.badge}>{badge}</span>}
                    {relativeTime(chat.updated_at, now, timeZone)}
                  </span>
                </span>
              </NavLink>
              <IconButton label={`Удалить чат: ${chat.title}`} onClick={() => setRemoving(chat)}>
                <Trash2 size={18} />
              </IconButton>
            </li>
          );
        })}
      </ul>

      {removing && (
        <Dialog
          title="Удалить чат?"
          width={420}
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setRemoving(null)}>
                Отмена
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() =>
                  remove.mutate(removing.id, {
                    onSuccess: () => {
                      setRemoving(null);
                      onDeleted(removing.id);
                    },
                    onError: (error) => {
                      setRemoving(null);
                      setFailure(failureMessage(error));
                    },
                  })
                }
              >
                Удалить
              </Button>
            </>
          }
        >
          <p>{removing.title}</p>
          {removing.state === "created" && (
            <p className={styles.note}>Созданная карточка останется на месте.</p>
          )}
        </Dialog>
      )}
    </aside>
  );
}
