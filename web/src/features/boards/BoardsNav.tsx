import { NavLink, useLocation } from "react-router";

import { BoardIcon } from "./BoardIcon";
import { useBoards } from "./api";
import styles from "./BoardsNav.module.css";

const itemClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? `${styles.item} ${styles.itemActive}` : styles.item;

/** "Мои доски" in the left panel, shown on the board screens only. */
export function BoardsNav() {
  const { pathname } = useLocation();
  const onBoards = pathname.startsWith("/boards");
  const { data: boards } = useBoards();
  if (!onBoards || !boards) return null;

  return (
    <nav className={styles.nav} aria-label="Мои доски">
      <p className={styles.title}>Мои доски</p>
      {boards.map((board) => (
        <NavLink key={board.id} to={`/boards/${board.id}`} className={itemClass}>
          <BoardIcon icon={board.icon} size={18} />
          <span className={styles.name}>{board.name}</span>
        </NavLink>
      ))}
    </nav>
  );
}
