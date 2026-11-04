import type { LabelColor, TaskActivity } from "../../api/client";

export const PRIORITIES: { value: 1 | 2 | 3 | 4; label: string; short: string }[] = [
  { value: 1, label: "P1 Срочно", short: "P1" },
  { value: 2, label: "P2 Высокий", short: "P2" },
  { value: 3, label: "P3 Обычный", short: "P3" },
  { value: 4, label: "P4 Низкий", short: "P4" },
];

export const LABEL_COLORS: { value: LabelColor; label: string }[] = [
  { value: "violet", label: "Фиолетовый" },
  { value: "blue", label: "Синий" },
  { value: "teal", label: "Бирюзовый" },
  { value: "green", label: "Зелёный" },
  { value: "yellow", label: "Жёлтый" },
  { value: "orange", label: "Оранжевый" },
  { value: "red", label: "Красный" },
  { value: "pink", label: "Розовый" },
];

export const ROLE_LABELS: Record<"owner" | "editor" | "viewer", string> = {
  owner: "Владелец",
  editor: "Редактор",
  viewer: "Читатель",
};

export const NOTIFICATION_TEXT: Record<string, (title: string) => string> = {
  event_added: (title) => `Новое совместное событие: ${title}`,
  event_updated: (title) => `Изменилось событие: ${title}`,
  event_deleted: (title) => `Событие удалено: ${title}`,
  event_removed: (title) => `Вас убрали из события: ${title}`,
  event_reminder: (title) => `Скоро начнётся: ${title}`,
  task_assigned: (title) => `Вам назначена задача: ${title}`,
  task_updated: (title) => `Изменилась задача: ${title}`,
  task_commented: (title) => `Новый комментарий: ${title}`,
  task_due: (title) => `Сегодня срок: ${title}`,
  task_reminder: (title) => `Напоминание о задаче: ${title}`,
  board_added: (title) => `Вас добавили на доску: ${title}`,
};

/** Russian plural form for a count: the word only, the caller prints the number. */
export function pluralize(count: number, one: string, few: string, many: string): string {
  const n = Math.abs(count);
  const lastTwo = n % 100;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  const last = n % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

/** The Russian name of each task field that an update can change, as the history shows it. */
const CHANGED_FIELDS = new Map<string, string>([
  ["title", "название"],
  ["description", "описание"],
  ["priority", "приоритет"],
  ["start_date", "дата начала"],
  ["due_date", "срок"],
  ["due_at", "срок"],
]);

/** A field of the activity data as text. Anything that is not a string reads as empty. */
function textOf(data: Record<string, unknown>, key: string): string {
  const value = data[key];
  return typeof value === "string" ? value : "";
}

function isBoardMove(data: Record<string, unknown>): boolean {
  return textOf(data, "from_board") !== "" && textOf(data, "to_board") !== "";
}

function moveText(data: Record<string, unknown>): string {
  const from = textOf(data, "from_column");
  const to = textOf(data, "to_column");
  if (isBoardMove(data)) {
    return `Перенос: ${textOf(data, "from_board")}, ${from} → ${textOf(data, "to_board")}, ${to}`;
  }
  return `Перенос: ${from} → ${to}`;
}

/** A completion or a reopening that also moved the card to another board says so after its usual text. */
function withMove(usual: string, data: Record<string, unknown>): string {
  return isBoardMove(data) ? `${usual}. ${moveText(data)}` : usual;
}

function changedField(change: unknown): string | undefined {
  if (typeof change !== "object" || change === null) return undefined;
  const field: unknown = (change as Record<string, unknown>).field;
  return typeof field === "string" ? field : undefined;
}

/** Each field is named once, in the order it first appears. A field it does not know is skipped. */
function updatedText(data: Record<string, unknown>): string {
  const changes: unknown = data.changes;
  const names = new Set<string>();
  if (Array.isArray(changes)) {
    for (const change of changes as unknown[]) {
      const field = changedField(change);
      const name = field === undefined ? undefined : CHANGED_FIELDS.get(field);
      if (name) names.add(name);
    }
  }
  return names.size > 0 ? `Изменено: ${[...names].join(", ")}` : "Изменено";
}

/** The line that the task history shows for one event. */
export function activityText(activity: Pick<TaskActivity, "kind" | "data">): string {
  const { kind, data } = activity;
  switch (kind) {
    case "created":
      return "Карточка создана";
    case "updated":
      return updatedText(data);
    case "moved":
      return moveText(data);
    case "completed":
      return withMove("Выполнено", data);
    case "reopened":
      return withMove("Возвращено в работу", data);
    case "assigned":
      return `Назначен исполнитель: ${textOf(data, "name")}`;
    case "unassigned":
      return `Снят исполнитель: ${textOf(data, "name")}`;
    case "labeled":
      return `Добавлена метка: ${textOf(data, "name")}`;
    case "unlabeled":
      return `Убрана метка: ${textOf(data, "name")}`;
    case "checklist_added":
      return `Новый пункт: ${textOf(data, "text")}`;
    case "checklist_checked":
      return `Пункт выполнен: ${textOf(data, "text")}`;
    case "checklist_unchecked":
      return `Пункт снова открыт: ${textOf(data, "text")}`;
    case "checklist_removed":
      return `Удалён пункт: ${textOf(data, "text")}`;
    case "event_linked":
      return `Связано с событием: ${textOf(data, "title")}`;
    case "event_unlinked":
      return `Связь с событием убрана: ${textOf(data, "title")}`;
    default:
      return "";
  }
}
