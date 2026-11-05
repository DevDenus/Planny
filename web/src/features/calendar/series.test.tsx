import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  API,
  apiError,
  bodyOf,
  json,
  makeEvent,
  makeNotification,
  path,
  renderApp,
  requestsTo,
  stubApp,
  type Stub,
} from "../tasks/testing";
import { newDraft, validate, type EventDraft } from "./EventForm";
import { resetCalendarFilters } from "./filters";

const DAY = "/calendar?day=2026-11-06";
const EVENTS = `${API}/events`;
const EVENT = `${EVENTS}/e1`;
const MONTHLY = { freq: "monthly", until: null, count: null } as const;

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetCalendarFilters();
});

function answering(method: string, pathname: string, answer: () => Response): Stub {
  return (request) =>
    request.method === method && path(request) === pathname ? answer() : undefined;
}

async function newEventForm() {
  renderApp(`${DAY}&event=new`);
  const form = within(await screen.findByRole("dialog", { name: "Новое событие" }));
  const user = userEvent.setup();
  await user.type(form.getByLabelText("Название"), "Зарядка");
  return { form, user };
}

async function postedBody(calls: Request[]) {
  await waitFor(() => expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(1));
  return bodyOf(requestsTo(calls, "POST", EVENTS)[0]!);
}

describe("creating a series", () => {
  const created = () => stubCreate();

  function stubCreate() {
    return stubApp({
      onRequest: answering("POST", EVENTS, () => json(201, makeEvent({ id: "new" }))),
    });
  }

  it("sends no series and no reminder by default", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    expect(form.queryByLabelText("Окончание серии")).not.toBeInTheDocument();
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await postedBody(calls)).toMatchObject({ recurrence: null, reminder_minutes: [] });
  });

  it("sends a series without an end", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждую неделю");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect((await postedBody(calls)).recurrence).toEqual({
      freq: "weekly",
      until: null,
      count: null,
    });
  });

  it("sends a series up to a date", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый месяц");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "До даты");
    await user.type(form.getByLabelText("Последний день"), "2027-12-31");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect((await postedBody(calls)).recurrence).toEqual({
      freq: "monthly",
      until: "2027-12-31",
      count: null,
    });
  });

  it("sends a number of repeats", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый день");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "N раз");
    await user.type(form.getByLabelText("Сколько раз"), "10");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect((await postedBody(calls)).recurrence).toEqual({
      freq: "daily",
      until: null,
      count: 10,
    });
  });

  it("sends the chosen reminder", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Напоминание"), "За 1 час");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect((await postedBody(calls)).reminder_minutes).toEqual([60]);
  });

  it("refuses a series without its last day and sends nothing", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый день");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "До даты");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await form.findByText("Укажите дату")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(0);
  });

  it("refuses a last day before the start", async () => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый день");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "До даты");
    await user.type(form.getByLabelText("Последний день"), "2026-11-01");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await form.findByText("Не раньше начала")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(0);
  });

  it.each(["", "0", "1001", "1.5"])("refuses %j as a number of repeats", async (count) => {
    const calls = created();
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый день");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "N раз");
    if (count) await user.type(form.getByLabelText("Сколько раз"), count);
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(await form.findByText("От 1 до 1000")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(0);
  });

  it("shows what the server says of the end of a series at its field", async () => {
    stubApp({
      onRequest: answering("POST", EVENTS, () =>
        apiError(422, "validation_error", "Ошибка в данных", {
          fields: { recurrence: "Серия не может закончиться раньше первого повтора" },
        }),
      ),
    });
    const { form, user } = await newEventForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый день");
    await user.selectOptions(form.getByLabelText("Окончание серии"), "До даты");
    await user.type(form.getByLabelText("Последний день"), "2027-01-01");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(
      await form.findByText("Серия не может закончиться раньше первого повтора"),
    ).toBeInTheDocument();
  });

  it("warns of skipped months only for a monthly series on a late day", async () => {
    const hint = "В месяцах без этого числа повтор пропускается";
    stubApp();
    renderApp("/calendar?day=2026-10-31&event=new&start=2026-10-31");
    const form = within(await screen.findByRole("dialog", { name: "Новое событие" }));
    const user = userEvent.setup();
    expect(form.queryByText(hint)).not.toBeInTheDocument();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждую неделю");
    expect(form.queryByText(hint)).not.toBeInTheDocument();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый месяц");
    expect(form.getByText(hint)).toBeInTheDocument();
  });

  it("doesn't warn on a day that every month has", async () => {
    stubApp();
    renderApp("/calendar?day=2026-11-28&event=new&start=2026-11-28");
    const form = within(await screen.findByRole("dialog", { name: "Новое событие" }));
    const user = userEvent.setup();

    await user.selectOptions(form.getByLabelText("Повторение"), "Каждый месяц");

    expect(form.queryByText(/пропускается/)).not.toBeInTheDocument();
  });
});

describe("editing a series", () => {
  const event = makeEvent({
    recurrence: { ...MONTHLY, until: "2027-12-31" },
    reminder_minutes: [15],
    version: 3,
  });

  function stubEdit() {
    return stubApp({
      events: [event],
      onRequest: answering("PATCH", EVENT, () => json(200, event)),
    });
  }

  async function editForm() {
    renderApp(`${DAY}&event=e1&edit=1`);
    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    return { form, user: userEvent.setup() };
  }

  async function patchedBody(calls: Request[]) {
    await waitFor(() => expect(requestsTo(calls, "PATCH", EVENT)).toHaveLength(1));
    return bodyOf(requestsTo(calls, "PATCH", EVENT)[0]!);
  }

  it("reads what the event has and says the whole series changes", async () => {
    stubEdit();
    const { form } = await editForm();

    expect(form.getByLabelText("Повторение")).toHaveValue("monthly");
    expect(form.getByLabelText("Окончание серии")).toHaveValue("until");
    expect(form.getByLabelText("Последний день")).toHaveValue("2027-12-31");
    expect(form.getByLabelText("Напоминание")).toHaveValue("15");
    expect(form.getByText("Изменения применятся ко всей серии")).toBeInTheDocument();
  });

  it("doesn't say so of a one-off event", async () => {
    stubApp({ events: [makeEvent()] });
    const { form } = await editForm();

    expect(form.queryByText("Изменения применятся ко всей серии")).not.toBeInTheDocument();
  });

  it("sends nothing of the series when it stays the same", async () => {
    const calls = stubEdit();
    const { form, user } = await editForm();

    await user.type(form.getByLabelText("Название"), "!");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    expect(await patchedBody(calls)).toEqual({ title: "Ужин вдвоём!", version: 3 });
  });

  it("sends the new end of the series", async () => {
    const calls = stubEdit();
    const { form, user } = await editForm();

    await user.selectOptions(form.getByLabelText("Окончание серии"), "Никогда");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    expect(await patchedBody(calls)).toEqual({
      recurrence: { freq: "monthly", until: null, count: null },
      version: 3,
    });
  });

  it("turns a series into a one-off event", async () => {
    const calls = stubEdit();
    const { form, user } = await editForm();

    await user.selectOptions(form.getByLabelText("Повторение"), "Не повторять");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    expect(await patchedBody(calls)).toEqual({ recurrence: null, version: 3 });
  });

  it("sends the reminder as a list, and an empty one for none", async () => {
    const calls = stubEdit();
    const { form, user } = await editForm();

    await user.selectOptions(form.getByLabelText("Напоминание"), "Нет");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    expect(await patchedBody(calls)).toEqual({ reminder_minutes: [], version: 3 });
  });
});

describe("checking the end of a series against the saved one", () => {
  const saved: EventDraft = {
    ...newDraft("u1", "2027-02-01", "09:00", "Ужин вдвоём"),
    repeat: "monthly",
    seriesEnd: "until",
    until: "2027-01-31",
  };

  it("keeps an end the server accepted when only the title changes", () => {
    expect(validate({ ...saved, title: "Ужин" }, saved).until).toBeUndefined();
  });

  it("refuses a changed end before the start", () => {
    expect(validate({ ...saved, until: "2027-01-30" }, saved).until).toBe("Не раньше начала");
  });

  it("refuses an unchanged end once the start moves past it", () => {
    expect(validate({ ...saved, startDate: "2027-02-02" }, saved).until).toBe("Не раньше начала");
  });

  it("refuses an end before the start when there is no saved event", () => {
    expect(validate(saved).until).toBe("Не раньше начала");
  });
});

describe("viewing a series", () => {
  it("names the rule and, of a one-off event, nothing", async () => {
    stubApp({ events: [makeEvent({ recurrence: { ...MONTHLY, count: 4 } })] });
    renderApp(`${DAY}&event=e1`);

    expect(await screen.findByText("Каждый месяц, 4 раза")).toBeInTheDocument();
  });

  it("shows the date of the repeat it was opened from", async () => {
    stubApp({ events: [makeEvent({ recurrence: MONTHLY })] });
    renderApp(`${DAY}&event=e1&occurrence=2027-03-06T16:00:00Z`);

    expect(await screen.findByText("Сб, 6 марта · 19:00 – 20:00")).toBeInTheDocument();
  });

  it("shows the first repeat when none is named", async () => {
    stubApp({ events: [makeEvent({ recurrence: MONTHLY })] });
    renderApp(`${DAY}&event=e1`);

    expect(await screen.findByText("Пт, 6 ноября · 19:00 – 20:00")).toBeInTheDocument();
  });

  it("changes the reminder at once, as the category", async () => {
    const event = makeEvent({ version: 2 });
    const calls = stubApp({
      events: [event],
      onRequest: answering("PATCH", EVENT, () => json(200, event)),
    });
    renderApp(`${DAY}&event=e1`);
    const dialog = within(await screen.findByRole("dialog", { name: event.title }));

    const user = userEvent.setup();
    await user.selectOptions(dialog.getByLabelText("Напоминание"), "За 30 минут");

    await waitFor(() => expect(requestsTo(calls, "PATCH", EVENT)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", EVENT)[0]!)).toEqual({
      reminder_minutes: [30],
      version: 2,
    });
  });

  const OTHER = { id: "u2", login: "zhenya", display_name: "Женя", color: "teal" };

  it.each([
    ["a one-off event", null, [], "Ужин вдвоём"],
    ["a shared event", null, [OTHER], "Событие удалится у всех участников"],
    ["a series", MONTHLY, [], "Будет удалена вся серия"],
    ["a shared series", MONTHLY, [OTHER], "Вся серия удалится у всех участников"],
  ])("warns of what goes when deleting %s", async (_, recurrence, others, warning) => {
    const event = makeEvent({ recurrence });
    event.participants = [...event.participants, ...others] as typeof event.participants;
    stubApp({ events: [event] });
    renderApp(`${DAY}&event=e1`);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Удалить" }));

    const confirm = within(await screen.findByRole("dialog", { name: "Удалить событие?" }));
    expect(confirm.getByText(warning)).toBeInTheDocument();
  });
});

describe("a reminder in the notification centre", () => {
  it("leads to the repeat it was about", async () => {
    const notification = makeNotification({
      kind: "event_reminder",
      title: "Зарядка",
      event_id: "e1",
      data: { occurrence_start: "2027-03-06T16:00:00+00:00" },
    });
    stubApp({
      events: [makeEvent({ title: "Зарядка", recurrence: MONTHLY })],
      notifications: [notification],
      onRequest: answering("POST", `${API}/notifications/${notification.id}/read`, () =>
        json(204, undefined),
      ),
    });
    renderApp("/calendar");
    const user = userEvent.setup();

    // The top bar and the mobile header have a bell each.
    const [bell] = await screen.findAllByRole("button", { name: "Уведомления" });
    await user.click(bell!);
    await user.click(await screen.findByText("Скоро начнётся: Зарядка"));

    expect(await screen.findByText("Сб, 6 марта · 19:00 – 20:00")).toBeInTheDocument();
  });
});
