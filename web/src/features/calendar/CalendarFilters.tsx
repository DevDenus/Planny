import { ListFilter } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router";

import { Dialog, IconButton, Switch } from "../../ui";
import { useCategories } from "./api";
import styles from "./CalendarFilters.module.css";
import { useCalendarFilters } from "./filters";

function FilterList() {
  const { data: categories } = useCategories();
  const { filters, setCategoryShown, setTasksShown } = useCalendarFilters();
  return (
    <>
      <p className={styles.title}>Категории</p>
      {categories?.map((category) => (
        <div key={category.id} className={styles.row}>
          <span className={styles.swatch} style={{ background: `var(--cat-${category.color})` }} />
          <Switch
            className={styles.switch}
            label={category.name}
            checked={!filters.hiddenCategories.includes(category.id)}
            onChange={(shown) => setCategoryShown(category.id, shown)}
          />
        </div>
      ))}
      <div className={styles.layer}>
        <Switch
          className={styles.switch}
          label="Задачи"
          checked={!filters.tasksHidden}
          onChange={setTasksShown}
        />
      </div>
    </>
  );
}

/** Categories and the task layer in the left panel, on the calendar screen only. */
export function CalendarNav() {
  const { pathname } = useLocation();
  if (!pathname.startsWith("/calendar")) return null;
  return (
    <nav className={styles.nav} aria-label="Категории">
      <FilterList />
    </nav>
  );
}

/** Where the left panel has no room for the list. */
export function FiltersButton() {
  const [open, setOpen] = useState(false);
  return (
    <span className={styles.button}>
      <IconButton label="Фильтры" onClick={() => setOpen(true)}>
        <ListFilter size={20} />
      </IconButton>
      {open && (
        <Dialog title="Фильтры" width={360} onClose={() => setOpen(false)}>
          <div className={styles.dialog}>
            <FilterList />
          </div>
        </Dialog>
      )}
    </span>
  );
}
