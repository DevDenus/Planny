import { Bell, CalendarDays, ListChecks, SquareKanban, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import type { Notification } from "../../api/client";
import { Avatar, Button, EmptyState, IconButton, LoadError, Skeleton, cx } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useEventParam } from "../calendar/eventLinks";
import { formatMoment } from "../tasks/dates";
import { NOTIFICATION_TEXT } from "../tasks/labels";
import { useTaskParam } from "../tasks/taskLinks";
import { useNotifications, useReadAllNotifications, useReadNotification } from "./api";
import styles from "./NotificationBell.module.css";

function KindIcon({ kind }: { kind: Notification["kind"] }) {
  if (kind.startsWith("task")) return <ListChecks size={18} aria-hidden="true" />;
  if (kind.startsWith("board")) return <SquareKanban size={18} aria-hidden="true" />;
  return <CalendarDays size={18} aria-hidden="true" />;
}

function occurrenceStart(item: Notification): string | undefined {
  const start = item.data.occurrence_start;
  return typeof start === "string" ? start : undefined;
}

function Row({ item, timeZone, onOpen }: RowProps) {
  const text = NOTIFICATION_TEXT[item.kind]?.(item.title) ?? item.title;
  return (
    <li>
      <button
        type="button"
        className={cx(styles.row, item.read_at === null && styles.unread)}
        onClick={() => onOpen(item)}
      >
        <span className={styles.kind}>
          <KindIcon kind={item.kind} />
        </span>
        <span className={styles.body}>
          <span>{text}</span>
          <span className={styles.meta}>
            {item.actor && (
              <Avatar name={item.actor.display_name} color={item.actor.color} size={20} />
            )}
            {formatMoment(item.created_at, new Date(), timeZone)}
          </span>
        </span>
        {item.read_at === null && (
          <span className={styles.dot} role="img" aria-label="Не прочитано" />
        )}
      </button>
    </li>
  );
}

type RowProps = {
  item: Notification;
  timeZone: string;
  onOpen: (item: Notification) => void;
};

function Panel({ onClose, unread }: { onClose: () => void; unread: number }) {
  const navigate = useNavigate();
  const { open: openTask } = useTaskParam();
  const { open: openEvent } = useEventParam();
  const { data: user } = useCurrentUser();
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useNotifications(true);
  const read = useReadNotification();
  const readAll = useReadAllNotifications();
  const items = data?.pages.flatMap((page) => page.items) ?? [];

  const openItem = (item: Notification) => {
    if (item.read_at === null) read.mutate(item.id);
    onClose();
    if (item.event_id) openEvent(item.event_id, occurrenceStart(item));
    else if (item.task_id) openTask(item.task_id);
    else if (item.board_id) void navigate(`/boards/${item.board_id}`);
  };

  return (
    <div className={styles.panel} role="dialog" aria-label="Уведомления">
      <header className={styles.header}>
        <h2 className={styles.title}>Уведомления</h2>
        <Button
          variant="ghost"
          // The count covers every page, while the loaded items may not reach the unread ones.
          disabled={unread === 0}
          loading={readAll.isPending}
          onClick={() => readAll.mutate()}
        >
          Прочитать всё
        </Button>
        <IconButton label="Закрыть" className={styles.close} onClick={onClose}>
          <X size={20} />
        </IconButton>
      </header>
      {isPending && <Skeleton height={64} />}
      {isError && (
        <div className={styles.error}>
          <LoadError message="Не удалось загрузить уведомления" onRetry={() => void refetch()} />
        </div>
      )}
      {!isPending && !isError && items.length === 0 && <EmptyState title="Уведомлений пока нет" />}
      {items.length > 0 && (
        <ul className={styles.list}>
          {items.map((item) => (
            <Row key={item.id} item={item} timeZone={user?.timezone ?? "UTC"} onOpen={openItem} />
          ))}
        </ul>
      )}
      {hasNextPage && (
        <Button variant="ghost" loading={isFetchingNextPage} onClick={() => void fetchNextPage()}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}

export function NotificationBell({ unread }: { unread: number }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={root} className={styles.bell}>
      <IconButton
        label="Уведомления"
        badge={unread}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Bell size={20} />
      </IconButton>
      {open && <Panel onClose={() => setOpen(false)} unread={unread} />}
    </div>
  );
}
