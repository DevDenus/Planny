import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { Button, IconButton } from "../../ui";
import { periodTitle, shiftDay, type CalendarView } from "./period";
import styles from "./PeriodHeader.module.css";

export type PeriodHeaderProps = {
  view: CalendarView;
  day: string;
  today: string;
  onDay: (day: string) => void;
  children?: ReactNode;
};

export function PeriodHeader({ view, day, today, onDay, children }: PeriodHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.arrows}>
        <IconButton label="Назад" onClick={() => onDay(shiftDay(view, day, -1))}>
          <ChevronLeft size={20} />
        </IconButton>
        <IconButton label="Вперёд" onClick={() => onDay(shiftDay(view, day, 1))}>
          <ChevronRight size={20} />
        </IconButton>
      </div>
      <h1 className={styles.title}>{periodTitle(view, day)}</h1>
      <Button variant="secondary" onClick={() => onDay(today)}>
        Сегодня
      </Button>
      {children}
    </header>
  );
}
