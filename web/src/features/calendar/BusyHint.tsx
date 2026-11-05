import type { CSSProperties } from "react";

import type { BusyInterval, UserSummary } from "../../api/client";
import { Avatar, Banner, Skeleton } from "../../ui";
import { addDays, clockTime, fromLocalInput } from "../tasks/dates";
import { useAvailability } from "./api";
import styles from "./BusyHint.module.css";

export type BusyHintProps = {
  people: UserSummary[]; // the participants, as the form lists them
  day: string; // YYYY-MM-DD: the day of the start, in the zone of the reader
  start: string | null; // ISO moment of the event, null while the form isn't complete
  end: string | null;
  timeZone: string;
  excludeEventId?: string; // the event being edited: it mustn't conflict with itself
};

const clamp = (moment: number, low: number, high: number) => Math.min(Math.max(moment, low), high);

/** Places an interval on the track of one day, as percentages, clipped to the day. */
export function trackBlock(
  startAt: string,
  endAt: string,
  dayStart: string,
  dayEnd: string,
): { left: number; width: number } {
  const first = Date.parse(dayStart);
  const last = Date.parse(dayEnd);
  const from = clamp(Date.parse(startAt), first, last);
  const to = clamp(Date.parse(endAt), first, last);
  const span = last - first;
  return { left: ((from - first) / span) * 100, width: (Math.max(to - from, 0) / span) * 100 };
}

/** True when the two half-open intervals share a moment. */
export function overlaps(
  leftStart: string,
  leftEnd: string,
  rightStart: string,
  rightEnd: string,
): boolean {
  return (
    Date.parse(leftStart) < Date.parse(rightEnd) && Date.parse(rightStart) < Date.parse(leftEnd)
  );
}

function blockStyle(
  startAt: string,
  endAt: string,
  dayStart: string,
  dayEnd: string,
): CSSProperties {
  const { left, width } = trackBlock(startAt, endAt, dayStart, dayEnd);
  return { left: `${left}%`, width: `${width}%` };
}

/** The busy times as text for the phone, where the track is hidden. */
function busyText(busy: BusyInterval[], timeZone: string): string {
  if (busy.length === 0) return "свободно";
  const spans = busy.map(
    (interval) =>
      `${clockTime(interval.start_at, timeZone)}–${clockTime(interval.end_at, timeZone)}`,
  );
  return `занято ${spans.join(", ")}`;
}

/** How busy the participants are on the day of the event, with a warning for a clash. */
export function BusyHint({ people, day, start, end, timeZone, excludeEventId }: BusyHintProps) {
  // The chosen day, from its midnight to the next one.
  const dayStart = fromLocalInput(day, "00:00", timeZone);
  const dayEnd = fromLocalInput(addDays(day, 1), "00:00", timeZone);
  // Without a complete event there is no period, and so no request. An event that runs past the
  // day asks up to its end, so that a clash after midnight is seen as well.
  const period =
    day !== "" && start !== null && end !== null
      ? { from: dayStart, to: Date.parse(end) > Date.parse(dayEnd) ? end : dayEnd }
      : null;
  const { data, isError } = useAvailability(
    people.map((person) => person.id),
    period,
    excludeEventId,
  );
  // The hint is optional, so a failed request shows nothing.
  if (people.length === 0 || period === null || start === null || end === null || isError) {
    return null;
  }

  const busyOf = (id: string): BusyInterval[] =>
    data?.find((item) => item.user_id === id)?.busy ?? [];
  // The track and the text show the busy times of the day only: a time after midnight is for the
  // next day, and would read as the morning of this one.
  const busyOnDay = (busy: BusyInterval[]): BusyInterval[] =>
    busy.filter((interval) => overlaps(interval.start_at, interval.end_at, dayStart, dayEnd));
  const clashing = people.filter((person) =>
    busyOf(person.id).some((busy) => overlaps(busy.start_at, busy.end_at, start, end)),
  );

  return (
    <div className={styles.hint}>
      <h3 className={styles.heading}>Занятость на этот день</h3>
      {data ? (
        <ul className={styles.rows}>
          {people.map((person) => {
            const busy = busyOnDay(busyOf(person.id));
            return (
              <li key={person.id} className={styles.row}>
                <Avatar name={person.display_name} color={person.color} size={24} />
                <span className={styles.name}>{person.display_name}</span>
                <div className={styles.lane}>
                  <div className={styles.track} aria-hidden="true">
                    {busy.map((interval) => (
                      <span
                        key={`${interval.start_at}/${interval.end_at}`}
                        className={styles.busy}
                        style={blockStyle(interval.start_at, interval.end_at, dayStart, dayEnd)}
                      />
                    ))}
                    <span
                      className={styles.event}
                      style={blockStyle(start, end, dayStart, dayEnd)}
                    />
                  </div>
                  <p className={styles.text}>{busyText(busy, timeZone)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <Skeleton height={48} />
      )}
      {clashing.length > 0 && (
        <Banner tone="warning">
          {`Пересечение по времени: ${clashing.map((person) => person.display_name).join(", ")}. Сохранить всё равно можно.`}
        </Banner>
      )}
    </div>
  );
}
