import { CalendarDays, ListChecks, Plus, Settings, Sparkles, SquareKanban } from "lucide-react";
import { Link, NavLink, Outlet, useLocation, useMatch } from "react-router";

import { Avatar, Logo } from "../../ui";
import { useAssistantStatus } from "../assistant/api";
import { useCurrentUser } from "../auth/session";
import { BoardsNav } from "../boards/BoardsNav";
import { CalendarNav } from "../calendar/CalendarFilters";
import { EventDialogHost } from "../calendar/EventDialog";
import { NotificationBell } from "../notifications/NotificationBell";
import { SearchBox, SearchButton } from "../search/SearchBox";
import { useSync } from "../sync/useSync";
import { TaskDialogHost } from "../tasks/TaskDialog";
import { newTaskSearch } from "../tasks/taskLinks";
import styles from "./AppShell.module.css";

const SECTIONS = [
  { to: "/calendar", label: "Календарь", Icon: CalendarDays },
  { to: "/tasks", label: "Задачи", Icon: ListChecks },
  { to: "/boards", label: "Доски", Icon: SquareKanban },
];
const ASSISTANT = { to: "/assistant", label: "Ассистент", Icon: Sparkles };
const SETTINGS = { to: "/settings", label: "Настройки", Icon: Settings };

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem;

const tabClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? `${styles.tab} ${styles.tabActive}` : styles.tab;

function AddTaskButton() {
  const { pathname } = useLocation();
  const onBoard = useMatch("/boards/:boardId");
  if (!pathname.startsWith("/tasks") && !pathname.startsWith("/boards")) return null;
  return (
    <Link
      className={styles.fab}
      to={{ search: newTaskSearch(onBoard?.params.boardId) }}
      aria-label="Новая задача"
    >
      <Plus size={26} aria-hidden="true" />
    </Link>
  );
}

export function AppShell() {
  const { data: user } = useCurrentUser();
  const { unread, disconnected } = useSync();
  // Hidden while the status loads or when it can't be read.
  const { data: assistant } = useAssistantStatus();
  const sections = assistant?.enabled ? [...SECTIONS, ASSISTANT] : SECTIONS;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandFull}>
            <Logo />
          </span>
          <span className={styles.brandCompact}>
            <Logo wordmark={false} />
          </span>
        </div>
        <nav className={styles.nav} aria-label="Разделы">
          {sections.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={navClass} title={label}>
              <Icon size={20} aria-hidden="true" />
              <span className={styles.navLabel}>{label}</span>
            </NavLink>
          ))}
        </nav>
        <CalendarNav />
        <BoardsNav />
        <div className={styles.sidebarBottom}>
          <NavLink to={SETTINGS.to} className={navClass} title={SETTINGS.label}>
            <SETTINGS.Icon size={20} aria-hidden="true" />
            <span className={styles.navLabel}>{SETTINGS.label}</span>
          </NavLink>
          {user && (
            <div className={styles.profile}>
              <Avatar name={user.display_name} color={user.color} />
              <span className={styles.navLabel}>{user.display_name}</span>
            </div>
          )}
        </div>
      </aside>

      <header className={styles.topbar}>
        <div className={styles.search}>
          <SearchBox />
        </div>
        <NotificationBell unread={unread} />
        {user && (
          <NavLink to={SETTINGS.to} className={styles.profileLink} aria-label="Профиль">
            <Avatar name={user.display_name} color={user.color} />
          </NavLink>
        )}
      </header>

      <header className={styles.mobileHeader}>
        <Logo />
        <div className={styles.mobileActions}>
          <SearchButton />
          <NotificationBell unread={unread} />
        </div>
      </header>

      <main className={styles.main}>
        {disconnected && (
          <p className={styles.disconnected} role="status">
            Нет связи с сервером
          </p>
        )}
        <Outlet />
      </main>

      <AddTaskButton />
      <TaskDialogHost />
      <EventDialogHost />

      <nav className={styles.tabs} aria-label="Разделы">
        {[...sections, SETTINGS].map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className={tabClass}>
            <Icon size={22} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
