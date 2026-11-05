import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BOARDS_KEY } from "../../api/queryClient";
import { releaseUpdates } from "../sync/hold";
import {
  API,
  USER,
  USER_SUMMARY,
  apiError,
  bodyOf,
  json,
  makeBoard,
  makeCategory,
  makeDeadline,
  makeEvent,
  makeNotification,
  makeOccurrence,
  makeTask,
  path,
  renderApp,
  requestsTo,
  searchOf,
  stubApp,
} from "../tasks/testing";
import { resetCalendarFilters } from "./filters";

const DAY = "/calendar?day=2026-11-06";
const ITEMS = `${API}/calendar/items`;
const EVENTS = `${API}/events`;
const ZHENYA = { id: "u2", display_name: "Женя", color: "violet" };
const board = makeBoard({ members: [USER_SUMMARY, ZHENYA] });

function answering(method: string, pathname: string, answer: () => Response) {
  return (request: Request) =>
    request.method === method && path(request) === pathname ? answer() : undefined;
}

async function openNewEvent(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Новое событие" }));
  return within(await screen.findByRole("dialog", { name: "Новое событие" }));
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetCalendarFilters();
});

afterEach(() => {
  releaseUpdates();
  vi.useRealTimers();
});

describe("the calendar screen", () => {
  it("asks for the whole month grid, from midnight to midnight in the zone of the user", async () => {
    const calls = stubApp();
    renderApp(DAY);

    await waitFor(() => expect(requestsTo(calls, "GET", ITEMS).length).toBeGreaterThan(0));
    const [request] = requestsTo(calls, "GET", ITEMS);
    expect(searchOf(request!).get("from")).toBe("2026-10-25T21:00:00Z");
    expect(searchOf(request!).get("to")).toBe("2026-12-06T21:00:00Z");
  });

  it("asks only for the week after switching to it, and keeps the view in the address", async () => {
    const calls = stubApp();
    const user = userEvent.setup();
    renderApp(DAY);

    await user.click(await screen.findByRole("radio", { name: "Неделя" }));

    await waitFor(() => {
      const request = requestsTo(calls, "GET", ITEMS).at(-1);
      expect(searchOf(request!).get("from")).toBe("2026-11-01T21:00:00Z");
      expect(searchOf(request!).get("to")).toBe("2026-11-08T21:00:00Z");
    });
    expect(screen.getByRole("heading", { name: "2 – 8 ноября 2026" })).toBeInTheDocument();
  });

  it("walks through months with the arrows and comes back to today", async () => {
    stubApp();
    const user = userEvent.setup();
    renderApp(DAY);
    expect(await screen.findByRole("heading", { name: "Ноябрь 2026" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Вперёд" }));
    expect(await screen.findByRole("heading", { name: "Декабрь 2026" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Сегодня" }));
    expect(screen.queryByRole("heading", { name: "Декабрь 2026" })).not.toBeInTheDocument();
  });

  it("lists the events and tasks of the chosen day in the panel", async () => {
    stubApp({
      categories: [makeCategory({ id: "c1" })],
      calendarItems: [
        makeOccurrence({ category_id: "c1" }),
        makeDeadline(),
        makeOccurrence({
          event_id: "other",
          title: "В другой день",
          start_at: "2026-11-09T16:00:00Z",
          end_at: "2026-11-09T17:00:00Z",
        }),
      ],
    });
    renderApp(DAY);

    const panel = within(
      (await screen.findByRole("heading", { name: "Пт, 6 ноября" })).parentElement!,
    );
    expect(await panel.findByText("Ужин вдвоём")).toBeInTheDocument();
    expect(panel.getByText("19:00 – 20:00")).toBeInTheDocument();
    expect(panel.getByText("Купить продукты")).toBeInTheDocument();
    expect(panel.queryByText("В другой день")).not.toBeInTheDocument();
  });

  it("marks a repeat of a series with an icon, and a one-off event without one", async () => {
    stubApp({
      calendarItems: [
        makeOccurrence({ event_id: "gym", title: "Зарядка", is_recurring: true }),
        makeOccurrence({
          event_id: "dentist",
          title: "Врач",
          start_at: "2026-11-06T10:00:00Z",
          end_at: "2026-11-06T11:00:00Z",
        }),
      ],
    });
    renderApp(DAY);

    const panel = within(
      (await screen.findByRole("heading", { name: "Пт, 6 ноября" })).parentElement!,
    );
    const gym = await panel.findByRole("button", { name: /Зарядка/ });
    expect(within(gym).getByRole("img", { name: "Повторяется" })).toBeInTheDocument();
    const dentist = panel.getByRole("button", { name: /Врач/ });
    expect(within(dentist).queryByRole("img", { name: "Повторяется" })).not.toBeInTheDocument();
  });

  it("hides a category and the task layer, and remembers it", async () => {
    stubApp({
      categories: [makeCategory({ id: "c1", name: "Работа" })],
      calendarItems: [makeOccurrence({ category_id: "c1" }), makeDeadline()],
    });
    const user = userEvent.setup();
    const first = renderApp(DAY);
    const panel = within(
      (await screen.findByRole("heading", { name: "Пт, 6 ноября" })).parentElement!,
    );
    await panel.findByText("Ужин вдвоём");

    const filters = within(screen.getByRole("navigation", { name: "Категории" }));
    await user.click(await filters.findByRole("switch", { name: "Работа" }));
    await user.click(filters.getByRole("switch", { name: "Задачи" }));

    expect(panel.queryByText("Ужин вдвоём")).not.toBeInTheDocument();
    expect(panel.queryByText("Купить продукты")).not.toBeInTheDocument();

    first.unmount();
    resetCalendarFilters();
    renderApp(DAY);
    const nav = within(await screen.findByRole("navigation", { name: "Категории" }));
    expect(await nav.findByRole("switch", { name: "Работа" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("marks a deadline done at once and undoes it when the server refuses", async () => {
    const calls = stubApp({
      boards: [makeBoard({ id: "b1" })],
      calendarItems: [makeDeadline()],
      onRequest: answering("POST", `${API}/tasks/t1/complete`, () =>
        apiError(403, "forbidden", "Доска доступна только для чтения"),
      ),
    });
    const user = userEvent.setup();
    renderApp(DAY);

    const box = await screen.findByRole("checkbox", { name: "Выполнить: Купить продукты" });
    // The box stays disabled until the boards are in, so wait for them before ticking it.
    await waitFor(() => expect(box).toBeEnabled());
    await user.click(box);

    await waitFor(() =>
      expect(requestsTo(calls, "POST", `${API}/tasks/t1/complete`)).toHaveLength(1),
    );
    expect(await screen.findByText("Доска доступна только для чтения")).toBeInTheDocument();
    expect(
      await screen.findByRole("checkbox", { name: "Выполнить: Купить продукты" }),
    ).not.toBeChecked();
  });

  it("disables the checkbox of a deadline on a board the user only views", async () => {
    stubApp({
      boards: [makeBoard({ id: "b1", my_role: "viewer", name: "Дом" })],
      calendarItems: [makeDeadline()],
    });
    const { client } = renderApp(DAY);

    await screen.findByRole("checkbox", { name: "Выполнить: Купить продукты" });
    // Disabled until the boards are in, so wait for them before reading its state.
    await waitFor(() =>
      expect(client.getQueryData([...BOARDS_KEY, "list", { archived: false }])).toBeDefined(),
    );
    expect(screen.getByRole("checkbox", { name: "Выполнить: Купить продукты" })).toBeDisabled();
  });

  it("enables the checkbox of a deadline on a board the user owns", async () => {
    stubApp({
      boards: [makeBoard({ id: "b1", name: "Дом" })],
      calendarItems: [makeDeadline()],
    });
    renderApp(DAY);

    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Выполнить: Купить продукты" })).toBeEnabled(),
    );
  });

  it("rereads the calendar when its counter grows, and when the tasks counter does", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const sync = { calendar: 0, tasks: 0, notifications: 0, unread_notifications: 0 };
    const calendarItems = [makeOccurrence()];
    const calls = stubApp({ sync, calendarItems });
    renderApp(DAY);
    await screen.findAllByText("Ужин вдвоём");
    await vi.advanceTimersByTimeAsync(5_100);
    const before = requestsTo(calls, "GET", ITEMS).length;

    calendarItems.push(makeOccurrence({ event_id: "e2", title: "Обед" }));
    sync.calendar += 1;
    await vi.advanceTimersByTimeAsync(5_100);

    expect((await screen.findAllByText("Обед")).length).toBeGreaterThan(0);
    const afterCalendar = requestsTo(calls, "GET", ITEMS).length;
    expect(afterCalendar).toBeGreaterThan(before);

    sync.tasks += 1;
    await vi.advanceTimersByTimeAsync(5_100);
    await waitFor(() =>
      expect(requestsTo(calls, "GET", ITEMS).length).toBeGreaterThan(afterCalendar),
    );
  });
});

describe("the event form", () => {
  it("creates an event of the chosen day with the moments in UTC", async () => {
    const calls = stubApp({
      onRequest: answering("POST", EVENTS, () => json(201, makeEvent())),
    });
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.type(form.getByLabelText("Название"), "  Ужин  ");
    await user.clear(form.getByLabelText("Время начала"));
    await user.type(form.getByLabelText("Время начала"), "19:00");
    await user.click(form.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(1));
    const body = await bodyOf(requestsTo(calls, "POST", EVENTS)[0]!);
    expect(body).toMatchObject({
      title: "Ужин",
      all_day: false,
      start_at: "2026-11-06T16:00:00Z",
      end_at: "2026-11-06T17:00:00Z",
      start_date: null,
      end_date: null,
      timezone: USER.timezone,
      participant_ids: [USER.id],
      category_id: null,
    });
    expect(body.id).toEqual(expect.any(String));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Новое событие" })).not.toBeInTheDocument(),
    );
  });

  it("sends dates and no moments for an all-day event", async () => {
    const calls = stubApp({
      onRequest: answering("POST", EVENTS, () => json(201, makeEvent())),
    });
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.type(form.getByLabelText("Название"), "День рождения");
    await user.click(form.getByRole("switch", { name: "Весь день" }));
    expect(form.queryByLabelText("Время начала")).not.toBeInTheDocument();
    await user.click(form.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", EVENTS)[0]!)).toMatchObject({
      all_day: true,
      start_date: "2026-11-06",
      end_date: "2026-11-06",
      start_at: null,
      end_at: null,
    });
  });

  it("adds the chosen people and keeps the author in the list", async () => {
    const calls = stubApp({
      boards: [board],
      onRequest: answering("POST", EVENTS, () => json(201, makeEvent())),
    });
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.type(form.getByLabelText("Название"), "Ужин");
    expect(form.getByRole("checkbox", { name: USER.display_name })).toBeDisabled();
    await user.click(await form.findByRole("checkbox", { name: "Женя" }));
    await user.click(form.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(1));
    const body = await bodyOf<{ participant_ids: string[] }>(requestsTo(calls, "POST", EVENTS)[0]!);
    expect(body.participant_ids.sort()).toEqual([USER.id, ZHENYA.id].sort());
  });

  it("refuses an end before the start without asking the server", async () => {
    const calls = stubApp();
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.type(form.getByLabelText("Название"), "Ужин");
    await user.clear(form.getByLabelText("Время конца"));
    await user.type(form.getByLabelText("Время конца"), "08:00");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await form.findByText("Конец должен быть позже начала")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(0);
  });

  it("takes the end along when the start moves past it", async () => {
    stubApp();
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.clear(form.getByLabelText("Время начала"));
    await user.type(form.getByLabelText("Время начала"), "20:00");

    expect(form.getByLabelText("Время конца")).toHaveValue("21:00");
  });

  it("keeps what was typed when the server refuses", async () => {
    stubApp({
      onRequest: answering("POST", EVENTS, () =>
        apiError(422, "validation_error", "Ошибка в данных", {
          fields: { end_at: "Конец должен быть позже начала" },
        }),
      ),
    });
    const user = userEvent.setup();
    renderApp(DAY);

    const form = await openNewEvent(user);
    await user.type(form.getByLabelText("Название"), "Ужин");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await form.findByText("Конец должен быть позже начала")).toBeInTheDocument();
    expect(form.getByLabelText("Название")).toHaveValue("Ужин");
  });

  it("sends only what changed, with the version", async () => {
    const event = makeEvent({ title: "Ужин", version: 4, description: "Дома" });
    const calls = stubApp({
      events: [event],
      onRequest: answering("PATCH", `${EVENTS}/e1`, () => json(200, event)),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Поздний ужин");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${EVENTS}/e1`)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", `${EVENTS}/e1`)[0]!)).toEqual({
      title: "Поздний ужин",
      version: 4,
    });
  });

  it("sends nothing when nothing changed", async () => {
    const calls = stubApp({ events: [makeEvent()] });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Изменить событие" })).not.toBeInTheDocument(),
    );
    expect(requestsTo(calls, "PATCH", `${EVENTS}/e1`)).toHaveLength(0);
  });

  it("offers the conflict dialog and saves over the new version on request", async () => {
    const newer = makeEvent({ title: "Чужое название", location: "Кафе", version: 2 });
    let answers = 0;
    const calls = stubApp({
      events: [makeEvent({ title: "Ужин" })],
      onRequest: answering("PATCH", `${EVENTS}/e1`, () => {
        answers += 1;
        return answers === 1
          ? apiError(409, "version_conflict", "Объект изменился", { current: newer })
          : json(200, newer);
      }),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Моё название");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    await user.click(await screen.findByRole("button", { name: "Сохранить мои изменения" }));

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${EVENTS}/e1`)).toHaveLength(2));
    expect(await bodyOf(requestsTo(calls, "PATCH", `${EVENTS}/e1`)[1]!)).toEqual({
      title: "Моё название",
      version: 2,
    });
  });

  it("loads the new version into the form when that is the choice", async () => {
    const newer = makeEvent({ title: "Чужое название", version: 2 });
    stubApp({
      events: [makeEvent({ title: "Ужин" })],
      onRequest: answering("PATCH", `${EVENTS}/e1`, () =>
        apiError(409, "version_conflict", "Объект изменился", { current: newer }),
      ),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Моё название");
    await user.click(form.getByRole("button", { name: "Сохранить" }));
    await user.click(await screen.findByRole("button", { name: "Показать новую версию" }));

    expect(form.getByLabelText("Название")).toHaveValue("Чужое название");
  });
});

describe("the event view", () => {
  it("shows the details and hides leaving from the only participant", async () => {
    stubApp({
      events: [
        makeEvent({
          location: "Ресторан",
          description: "Обсудить выходные",
          linked_tasks: [makeTask({ title: "Купить цветы" })],
        }),
      ],
    });
    renderApp(`${DAY}&event=e1`);

    const view = within(await screen.findByRole("dialog", { name: "Ужин вдвоём" }));
    expect(view.getByText("Пт, 6 ноября · 19:00 – 20:00")).toBeInTheDocument();
    expect(view.getByText("Ресторан")).toBeInTheDocument();
    expect(view.getByText("Обсудить выходные")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Купить цветы" })).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Выйти из события" })).not.toBeInTheDocument();
  });

  it("warns that a joint event is deleted for everyone", async () => {
    const calls = stubApp({
      events: [makeEvent({ participants: [USER_SUMMARY, ZHENYA] })],
      onRequest: answering("DELETE", `${EVENTS}/e1`, () => new Response(null, { status: 204 })),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1`);

    const view = within(await screen.findByRole("dialog", { name: "Ужин вдвоём" }));
    await user.click(view.getByRole("button", { name: "Удалить" }));
    const confirm = within(await screen.findByRole("dialog", { name: "Удалить событие?" }));
    expect(confirm.getByText("Событие удалится у всех участников")).toBeInTheDocument();
    await user.click(confirm.getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(requestsTo(calls, "DELETE", `${EVENTS}/e1`)).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Ужин вдвоём" })).not.toBeInTheDocument(),
    );
  });

  it("leaves a joint event", async () => {
    const url = `${EVENTS}/e1/participants/me`;
    const calls = stubApp({
      events: [makeEvent({ participants: [USER_SUMMARY, ZHENYA] })],
      onRequest: answering("DELETE", url, () => new Response(null, { status: 204 })),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1`);

    const view = within(await screen.findByRole("dialog", { name: "Ужин вдвоём" }));
    await user.click(view.getByRole("button", { name: "Выйти из события" }));

    await waitFor(() => expect(requestsTo(calls, "DELETE", url)).toHaveLength(1));
  });

  it("changes the personal category with the version of what it was read with", async () => {
    const calls = stubApp({
      categories: [makeCategory({ id: "c1" })],
      events: [makeEvent({ version: 3 })],
      onRequest: answering("PATCH", `${EVENTS}/e1`, () =>
        json(200, makeEvent({ category_id: "c1" })),
      ),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1`);

    const view = within(await screen.findByRole("dialog", { name: "Ужин вдвоём" }));
    await view.findByRole("option", { name: "Личное" });
    await user.selectOptions(view.getByLabelText("Категория"), "c1");

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${EVENTS}/e1`)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", `${EVENTS}/e1`)[0]!)).toEqual({
      category_id: "c1",
      version: 3,
    });
  });

  it("says so when the event no longer exists", async () => {
    stubApp();
    renderApp(`${DAY}&event=gone`);
    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
  });

  it("opens from a notification", async () => {
    stubApp({
      boards: [makeBoard({ is_default: true })],
      events: [makeEvent()],
      notifications: [
        makeNotification({ kind: "event_added", title: "Ужин вдвоём", event_id: "e1" }),
      ],
    });
    const user = userEvent.setup();
    renderApp("/calendar");

    const [bell] = await screen.findAllByRole("button", { name: "Уведомления" });
    await user.click(bell!);
    await user.click(await screen.findByText("Новое совместное событие: Ужин вдвоём"));

    expect(await screen.findByRole("dialog", { name: "Ужин вдвоём" })).toBeInTheDocument();
  });
});

describe("links with tasks", () => {
  const task = makeTask({ id: "t1", title: "Купить цветы", board_id: board.id });

  it("finds an event from the task form and links it", async () => {
    const url = `${API}/tasks/t1/event-links`;
    const found = {
      id: "e1",
      title: "Ужин",
      all_day: false,
      start_at: "2026-11-06T16:00:00Z",
      start_date: null,
      is_recurring: false,
      next_occurrence_start: null,
    };
    const calls = stubApp({
      boards: [board],
      tasks: [task],
      searchResults: { events: [found], tasks: [] },
      onRequest: answering("POST", url, () => new Response(null, { status: 204 })),
    });
    const user = userEvent.setup();
    renderApp("/tasks?task=t1");

    await user.type(await screen.findByLabelText("Найти событие"), "Ужин");
    await user.click(await screen.findByRole("button", { name: /Ужин/ }));

    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", url)[0]!)).toEqual({ event_id: "e1" });
  });

  it("creates an event for the task and links them", async () => {
    const dated = { ...task, due_date: "2026-11-06" };
    const url = `${API}/tasks/t1/event-links`;
    const calls = stubApp({
      boards: [board],
      tasks: [dated],
      onRequest: (request) =>
        answering("POST", EVENTS, () => json(201, makeEvent({ id: "new" })))(request) ??
        answering("POST", url, () => new Response(null, { status: 204 }))(request),
    });
    const user = userEvent.setup();
    renderApp("/tasks?task=t1");

    await user.click(await screen.findByRole("button", { name: "Создать событие" }));
    const eventForm = within(await screen.findByRole("dialog", { name: "Новое событие" }));
    expect(eventForm.getByLabelText("Название")).toHaveValue("Купить цветы");
    expect(eventForm.getByLabelText("Начало")).toHaveValue("2026-11-06");
    await user.click(eventForm.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", url)[0]!)).toEqual({ event_id: "new" });
    // The task form underneath stays open.
    expect(screen.getByRole("dialog", { name: "Задача" })).toBeInTheDocument();
  });

  it("removes a link", async () => {
    const url = `${API}/tasks/t1/event-links/e1`;
    const linked = {
      ...task,
      linked_events: [
        {
          id: "e1",
          title: "Ужин",
          all_day: false,
          start_at: "2026-11-06T16:00:00Z",
          start_date: null,
          is_recurring: false,
          next_occurrence_start: null,
        },
      ],
    };
    const calls = stubApp({
      boards: [board],
      tasks: [linked],
      onRequest: answering("DELETE", url, () => new Response(null, { status: 204 })),
    });
    const user = userEvent.setup();
    renderApp("/tasks?task=t1");

    await user.click(await screen.findByRole("button", { name: "Убрать связь: Ужин" }));

    await waitFor(() => expect(requestsTo(calls, "DELETE", url)).toHaveLength(1));
  });

  it("shows the next repeat of a linked series, not its first one", async () => {
    const linked = {
      ...task,
      linked_events: [
        {
          id: "e1",
          title: "Ужин",
          all_day: false,
          start_at: "2026-11-06T16:00:00Z",
          start_date: null,
          is_recurring: true,
          next_occurrence_start: "2026-11-13T16:00:00Z",
        },
      ],
    };
    stubApp({ boards: [board], tasks: [linked] });
    renderApp("/tasks?task=t1");

    const link = await screen.findByRole("button", { name: /^Ужин/ });
    await waitFor(() => expect(link).toHaveTextContent("Пт, 13 ноября, 19:00"));
    expect(link).not.toHaveTextContent("6 ноября");
  });

  it("opens a linked task instead of the event", async () => {
    stubApp({
      boards: [board],
      tasks: [task],
      events: [makeEvent({ linked_tasks: [task] })],
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=e1`);

    const view = within(await screen.findByRole("dialog", { name: "Ужин вдвоём" }));
    await user.click(view.getByRole("button", { name: "Купить цветы" }));

    expect(await screen.findByRole("dialog", { name: "Задача" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Ужин вдвоём" })).not.toBeInTheDocument();
  });

  it("offers no link controls on a read-only board", async () => {
    const readOnly = { ...board, my_role: "viewer" as const };
    stubApp({ boards: [readOnly], tasks: [task] });
    renderApp("/tasks?task=t1");

    await screen.findByRole("dialog", { name: "Задача" });
    await screen.findByText("Доска доступна только для чтения");
    expect(screen.queryByLabelText("Найти событие")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Создать событие" })).not.toBeInTheDocument();
  });
});
