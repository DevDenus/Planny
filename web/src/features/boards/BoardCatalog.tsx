import { ChevronRight } from "lucide-react";
import { Link } from "react-router";

import type { Board } from "../../api/client";
import { Skeleton } from "../../ui";
import { pluralize } from "../tasks/labels";
import { BoardIcon } from "./BoardIcon";
import styles from "./BoardCatalog.module.css";

export function openTasksLabel(count: number): string {
  return `${count} ${pluralize(count, "задача", "задачи", "задач")}`;
}

/** The block from the right panel of the tasks screen. */
export function BoardCatalog({ boards }: { boards: Board[] | undefined }) {
  if (!boards) return <Skeleton height={60} />;
  return (
    <ul className={styles.list}>
      {boards.map((board) => (
        <li key={board.id}>
          <Link className={styles.board} to={`/boards/${board.id}`}>
            <span className={styles.icon}>
              <BoardIcon icon={board.icon} />
            </span>
            <span className={styles.text}>
              <span className={styles.name}>{board.name}</span>
              <span className={styles.count}>{openTasksLabel(board.open_tasks_count)}</span>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
