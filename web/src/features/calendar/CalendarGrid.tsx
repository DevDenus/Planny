import FullCalendar from "@fullcalendar/react";
import type { CalendarRef, DateClickInfo, DayHeaderInfo } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import interactionPlugin from "@fullcalendar/react/interaction";
import ruLocale from "@fullcalendar/react/locales/ru";
import classicTheme from "@fullcalendar/react/themes/classic";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import { CheckSquare, Repeat, Square, Users } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import type { CalendarItem, CategoryColor } from "../../api/client";
import { cx } from "../../ui";
import { clockTime } from "../tasks/dates";
import styles from "./CalendarGrid.module.css";
import { eventTime, gridInput, wallClock } from "./items";
import { dayHeading, type CalendarView } from "./period";
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";

const PLUGINS = [dayGridPlugin, timeGridPlugin, interactionPlugin, classicTheme];
const GRID_VIEWS: Record<CalendarView, string> = {
  month: "dayGridMonth",
  week: "timeGridWeek",
  day: "timeGridDay",
};

/** Half an hour: tall enough for one line, so a short event keeps its title. */
const SLOT_HEIGHT = 26;

const isoDay = (date: Date) => date.toISOString().slice(0, 10);

function itemOf(extendedProps: Record<string, unknown>): CalendarItem {
  return extendedProps.item as CalendarItem;
}

function GridItem({ item, timeZone }: { item: CalendarItem; timeZone: string }) {
  if (item.type === "task") {
    const Icon = item.completed_at === null ? Square : CheckSquare;
    return (
      <span className={styles.task}>
        <Icon size={14} aria-hidden="true" />
        <span className={styles.title} title={item.title}>
          {item.title}
        </span>
        {item.due_at !== null && (
          <span className={styles.taskTime}>{clockTime(item.due_at, timeZone)}</span>
        )}
      </span>
    );
  }
  const shared = item.participants.length > 1;
  return (
    <span className={styles.event}>
      <span className={styles.title} title={item.title}>
        {item.title}
      </span>
      {!item.all_day && <span className={styles.time}>{eventTime(item, timeZone)}</span>}
      {(item.is_recurring || shared) && (
        <span className={styles.marks}>
          {item.is_recurring && <Repeat size={13} role="img" aria-label="Повторяется" />}
          {shared && <Users size={13} role="img" aria-label="Совместное" />}
        </span>
      )}
    </span>
  );
}

function DayHeader({ info, view }: { info: DayHeaderInfo; view: CalendarView }) {
  const { weekday, date } = dayHeading(isoDay(info.date));
  return (
    <span className={styles.dayHeader}>
      <span className={styles.weekday}>{weekday}</span>
      {view !== "month" && <span className={styles.date}>{date}</span>}
    </span>
  );
}

export type CalendarGridProps = {
  view: CalendarView;
  day: string;
  items: CalendarItem[];
  colors: Map<string, CategoryColor>;
  timeZone: string;
  now: Date;
  onSelectDay: (day: string) => void;
  /** Present where a click on an empty hour creates an event. */
  onCreateAt?: (day: string, time: string) => void;
  onOpenItem: (item: CalendarItem) => void;
};

export function CalendarGrid({
  view,
  day,
  items,
  colors,
  timeZone,
  now,
  onSelectDay,
  onCreateAt,
  onOpenItem,
}: CalendarGridProps) {
  const calendar = useRef<CalendarRef>(null);
  const inputs = useMemo(
    () => items.map((item) => gridInput(item, timeZone, colors)),
    [items, timeZone, colors],
  );

  useEffect(() => {
    calendar.current?.getApi().changeView(GRID_VIEWS[view], day);
  }, [view, day]);

  const dateClick = (info: DateClickInfo) => {
    const [date = "", time = ""] = info.dateStr.split("T");
    if (info.allDay || !onCreateAt) onSelectDay(date);
    else onCreateAt(date, time.slice(0, 5));
  };

  return (
    <div className={styles.grid}>
      <FullCalendar
        ref={calendar}
        plugins={PLUGINS}
        locale={ruLocale}
        timeZone="UTC"
        now={wallClock(now, timeZone)}
        initialView={GRID_VIEWS[view]}
        initialDate={day}
        headerToolbar={false}
        firstDay={1}
        height="100%"
        dayMaxEvents
        moreLinkClick={(info) => onSelectDay(isoDay(info.date))}
        nowIndicator
        allDayText="Весь день"
        slotDuration="00:30:00"
        slotHeaderInterval="01:00:00"
        slotHeaderFormat={{ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }}
        slotMinHeight={SLOT_HEIGHT}
        slotEventOverlap={false}
        scrollTime="08:00:00"
        eventOrder="order,start,-duration,title"
        events={inputs}
        eventDisplay="block"
        eventClass={(info) => {
          const item = itemOf(info.event.extendedProps);
          return cx(styles.item, item.type === "task" && item.completed_at && styles.done);
        }}
        eventContent={(info) => (
          <GridItem item={itemOf(info.event.extendedProps)} timeZone={timeZone} />
        )}
        eventClick={(info) => onOpenItem(itemOf(info.event.extendedProps))}
        dateClick={dateClick}
        dayHeaderContent={(info) => <DayHeader info={info} view={view} />}
        dayHeaderClass={(info) => cx(view !== "month" && info.isToday && styles.today)}
        dayCellClass={(info) => cx(isoDay(info.date) === day && styles.selected)}
        dayCellTopClass={styles.dayTop}
      />
    </div>
  );
}
