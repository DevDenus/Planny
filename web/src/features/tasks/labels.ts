export const PRIORITIES: { value: 1 | 2 | 3 | 4; label: string; short: string }[] = [
  { value: 1, label: "P1 Срочно", short: "P1" },
  { value: 2, label: "P2 Высокий", short: "P2" },
  { value: 3, label: "P3 Обычный", short: "P3" },
  { value: 4, label: "P4 Низкий", short: "P4" },
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
