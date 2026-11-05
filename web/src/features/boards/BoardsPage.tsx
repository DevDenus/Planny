import { Archive, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import type { Board } from "../../api/client";
import { Avatar, Button, EmptyState, LoadError, Panel, Skeleton, Switch } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { BoardDialog } from "./BoardDialog";
import { openTasksLabel } from "./BoardCatalog";
import { BoardIcon } from "./BoardIcon";
import { useBoards } from "./api";
import styles from "./BoardsPage.module.css";

function BoardCard({ board }: { board: Board }) {
  return (
    <li>
      <Link className={styles.card} to={`/boards/${board.id}`}>
        <span className={styles.icon}>
          <BoardIcon icon={board.icon} size={22} />
        </span>
        <span className={styles.text}>
          <span className={styles.name}>{board.name}</span>
          <span className={styles.count}>{openTasksLabel(board.open_tasks_count)}</span>
        </span>
        {board.is_shared && (
          <span className={styles.members}>
            {board.members.map((user) => (
              <Avatar key={user.id} name={user.display_name} color={user.color} size={26} />
            ))}
          </span>
        )}
      </Link>
    </li>
  );
}

function Section({ title, boards }: { title: string; boards: Board[] }) {
  if (boards.length === 0) return null;
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      <ul className={styles.grid}>
        {boards.map((board) => (
          <BoardCard key={board.id} board={board} />
        ))}
      </ul>
    </section>
  );
}

export function BoardsPage() {
  const { data: user } = useCurrentUser();
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data: boards, isPending, isError, refetch } = useBoards(archived);

  const mine = (board: Board) => board.is_default && board.members[0]?.id === user?.id;
  const personal = [...(boards ?? []).filter((board) => !board.is_shared)].sort(
    (a, b) => Number(mine(b)) - Number(mine(a)),
  );
  const shared = (boards ?? []).filter((board) => board.is_shared);

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Доски</h1>
        <Switch label="Архивные" checked={archived} onChange={setArchived} />
        <Button
          className={styles.create}
          icon={<Plus size={18} />}
          onClick={() => setCreating(true)}
        >
          Новая доска
        </Button>
      </header>

      {isPending && <Skeleton height={68} />}
      {isError && (
        <Panel>
          <LoadError message="Не удалось загрузить доски" onRetry={() => void refetch()} />
        </Panel>
      )}
      {boards?.length === 0 && (
        <EmptyState
          title={archived ? "В архиве пусто" : "Досок нет"}
          action={
            !archived && (
              <Button variant="secondary" onClick={() => setCreating(true)}>
                Новая доска
              </Button>
            )
          }
        >
          {archived && <Archive size={20} aria-hidden="true" />}
        </EmptyState>
      )}
      <Section title="Личные" boards={personal} />
      <Section title="Общие" boards={shared} />

      {creating && <BoardDialog onClose={() => setCreating(false)} />}
    </section>
  );
}
