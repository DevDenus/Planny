import { Bell, CalendarDays, ListChecks, Search, Settings, SquareKanban } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { Avatar, IconButton, Logo } from "../../ui";
import { useCurrentUser } from "../auth/session";
import styles from "./AppShell.module.css";

const SECTIONS = [
  { to: "/calendar", label: "Календарь", Icon: CalendarDays },
  { to: "/tasks", label: "Задачи", Icon: ListChecks },
  { to: "/boards", label: "Доски", Icon: SquareKanban },
];
const SETTINGS = { to: "/settings", label: "Настройки", Icon: Settings };

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem;

const tabClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? `${styles.tab} ${styles.tabActive}` : styles.tab;

/** Search arrives with the calendar, notifications with the boards. */
const NOT_YET = "Появится позже";

export function AppShell() {
  const { data: user } = useCurrentUser();

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
          {SECTIONS.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={navClass} title={label}>
              <Icon size={20} aria-hidden="true" />
              <span className={styles.navLabel}>{label}</span>
            </NavLink>
          ))}
        </nav>
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
        <label className={styles.search}>
          <Search size={18} aria-hidden="true" />
          <input type="search" placeholder="Поиск" aria-label="Поиск" disabled title={NOT_YET} />
        </label>
        <IconButton label="Уведомления" disabled title={NOT_YET}>
          <Bell size={20} />
        </IconButton>
        {user && (
          <NavLink to={SETTINGS.to} className={styles.profileLink} aria-label="Профиль">
            <Avatar name={user.display_name} color={user.color} />
          </NavLink>
        )}
      </header>

      <header className={styles.mobileHeader}>
        <Logo />
        <div className={styles.mobileActions}>
          <IconButton label="Поиск" disabled title={NOT_YET}>
            <Search size={20} />
          </IconButton>
          <IconButton label="Уведомления" disabled title={NOT_YET}>
            <Bell size={20} />
          </IconButton>
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>

      <nav className={styles.tabs} aria-label="Разделы">
        {[...SECTIONS, SETTINGS].map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className={tabClass}>
            <Icon size={22} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
