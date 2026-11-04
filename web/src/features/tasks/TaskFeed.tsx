import { useState, type FormEvent } from "react";

import type { Board, Task, TaskComment } from "../../api/client";
import { Avatar, Banner, Button, SegmentedControl, Skeleton, TextArea } from "../../ui";
import { useCurrentUser } from "../auth/session";
import {
  failureMessage,
  useActivity,
  useAddComment,
  useComments,
  useDeleteComment,
  useUpdateComment,
} from "./api";
import { formatMoment } from "./dates";
import { activityText } from "./labels";
import styles from "./TaskFeed.module.css";

const BODY_MAX_LENGTH = 5000;
const TABS = [
  { value: "comments" as const, label: "Комментарии" },
  { value: "history" as const, label: "История" },
];

type TaskFeedProps = {
  task: Task;
  board: Board;
  readOnly: boolean;
  timeZone: string;
};

type CommentRowProps = {
  taskId: string;
  comment: TaskComment;
  mine: boolean;
  canDelete: boolean;
  timeZone: string;
};

function CommentRow({ taskId, comment, mine, canDelete, timeZone }: CommentRowProps) {
  const update = useUpdateComment(taskId);
  const remove = useDeleteComment(taskId);
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(comment.body);
  const failed = update.error ?? remove.error;

  const save = () => {
    if (!body.trim()) return;
    update.mutate(
      { commentId: comment.id, body: body.trim() },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <li className={styles.record}>
      <Avatar name={comment.author.display_name} color={comment.author.color} size={28} />
      <div className={styles.content}>
        <p className={styles.caption}>
          <span className={styles.author}>{comment.author.display_name}</span>
          <span>{formatMoment(comment.created_at, new Date(), timeZone)}</span>
          {comment.edited_at && <span>изменено</span>}
        </p>
        {failed && <Banner tone="error">{failureMessage(failed)}</Banner>}
        {editing ? (
          <>
            <TextArea
              hideLabel
              label="Текст комментария"
              value={body}
              maxLength={BODY_MAX_LENGTH}
              onChange={(event) => setBody(event.target.value)}
            />
            <div className={styles.actions}>
              <Button
                variant="secondary"
                onClick={() => {
                  setBody(comment.body);
                  setEditing(false);
                }}
              >
                Отмена
              </Button>
              <Button loading={update.isPending} disabled={!body.trim()} onClick={save}>
                Сохранить
              </Button>
            </div>
          </>
        ) : (
          <p className={styles.body}>{comment.body}</p>
        )}
        {!editing && (mine || canDelete) && (
          <div className={styles.links}>
            {mine && (
              <Button
                variant="ghost"
                onClick={() => {
                  setBody(comment.body);
                  setEditing(true);
                }}
              >
                Изменить
              </Button>
            )}
            <Button
              variant="ghost"
              loading={remove.isPending}
              onClick={() => remove.mutate(comment.id)}
            >
              Удалить
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}

function Comments({ task, board, readOnly, timeZone }: TaskFeedProps) {
  const { data: user } = useCurrentUser();
  const comments = useComments(task.id);
  const add = useAddComment(task.id);
  const [body, setBody] = useState("");
  // One id per text, so a retry after a lost response can't post the comment twice.
  const [id, setId] = useState(() => crypto.randomUUID());
  const items = comments.data?.pages.flatMap((page) => page.items) ?? [];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim()) return;
    add.mutate(
      { id, body: body.trim() },
      {
        onSuccess: () => {
          setBody("");
          setId(crypto.randomUUID());
        },
      },
    );
  };

  return (
    <>
      {comments.isPending && <Skeleton height={64} />}
      {comments.isError && <Banner tone="error">Не удалось загрузить комментарии</Banner>}
      {comments.isSuccess && items.length === 0 && (
        <p className={styles.empty}>Комментариев пока нет</p>
      )}
      {items.length > 0 && (
        <ul className={styles.records}>
          {items.map((comment) => (
            <CommentRow
              key={comment.id}
              taskId={task.id}
              comment={comment}
              mine={!readOnly && comment.author.id === user?.id}
              canDelete={!readOnly && board.my_role === "owner"}
              timeZone={timeZone}
            />
          ))}
        </ul>
      )}
      {comments.hasNextPage && (
        <Button
          variant="ghost"
          loading={comments.isFetchingNextPage}
          onClick={() => void comments.fetchNextPage()}
        >
          Показать ещё
        </Button>
      )}
      {!readOnly && (
        <form className={styles.composer} onSubmit={submit} noValidate>
          {add.error && <Banner tone="error">{failureMessage(add.error)}</Banner>}
          <TextArea
            hideLabel
            label="Новый комментарий"
            placeholder="Написать комментарий"
            value={body}
            maxLength={BODY_MAX_LENGTH}
            onChange={(event) => setBody(event.target.value)}
          />
          <Button type="submit" loading={add.isPending} disabled={!body.trim()}>
            Отправить
          </Button>
        </form>
      )}
    </>
  );
}

function History({ taskId, timeZone }: { taskId: string; timeZone: string }) {
  const activity = useActivity(taskId);
  const items = activity.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      {activity.isPending && <Skeleton height={64} />}
      {activity.isError && <Banner tone="error">Не удалось загрузить историю</Banner>}
      {items.length > 0 && (
        <ul className={styles.records}>
          {items.map((record) => (
            <li key={record.id} className={styles.record}>
              <Avatar name={record.actor.display_name} color={record.actor.color} size={28} />
              <div className={styles.content}>
                <p className={styles.caption}>
                  <span className={styles.author}>{record.actor.display_name}</span>
                  <span>{formatMoment(record.created_at, new Date(), timeZone)}</span>
                </p>
                <p className={styles.body}>{activityText(record)}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {activity.hasNextPage && (
        <Button
          variant="ghost"
          loading={activity.isFetchingNextPage}
          onClick={() => void activity.fetchNextPage()}
        >
          Показать ещё
        </Button>
      )}
    </>
  );
}

export function TaskFeed(props: TaskFeedProps) {
  const [tab, setTab] = useState<"comments" | "history">("comments");
  return (
    <section className={styles.feed} aria-label="Комментарии и история">
      <SegmentedControl label="Раздел карточки" value={tab} options={TABS} onChange={setTab} />
      {tab === "comments" ? (
        <Comments {...props} />
      ) : (
        <History taskId={props.task.id} timeZone={props.timeZone} />
      )}
    </section>
  );
}
