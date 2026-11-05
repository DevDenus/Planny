import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CALENDAR_KEY } from "../../api/queryClient";
import {
  API,
  USER,
  apiError,
  bodyOf,
  json,
  makeEvent,
  path,
  renderApp,
  requestsTo,
  stubApp,
  type Stub,
} from "../tasks/testing";
import { resetCalendarFilters } from "./filters";

const DAY = "/calendar?day=2026-11-06";
const EVENTS = `${API}/events`;
const EVENT = `${EVENTS}/e1`;
const TASK_LINKS = `${API}/tasks/t1/event-links`;
const GONE = "Событие удалили, пока вы его редактировали";

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetCalendarFilters();
});

/** Answers the request when it has this method and path, and lets every other one through. */
function answering(method: string, pathname: string, answer: () => Response): Stub {
  return (request) =>
    request.method === method && path(request) === pathname ? answer() : undefined;
}

describe("an event deleted in the background", () => {
  it("is said to be gone in place of the viewed event", async () => {
    const events = [makeEvent({ description: "Обсудить выходные" })];
    stubApp({ events });
    const { client } = renderApp(`${DAY}&event=e1`);
    expect(await screen.findByText("Обсудить выходные")).toBeInTheDocument();

    // The next read of the event answers 404, as after a deletion or a revoked access.
    events.length = 0;
    await act(() => client.invalidateQueries({ queryKey: CALENDAR_KEY }));

    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
    expect(screen.queryByText("Обсудить выходные")).not.toBeInTheDocument();
  });

  it("keeps the typed text of the form and says so above it", async () => {
    const events = [makeEvent({ title: "Ужин" })];
    stubApp({ events });
    const user = userEvent.setup();
    const { client } = renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Поздний ужин");

    events.length = 0;
    await act(() => client.invalidateQueries({ queryKey: CALENDAR_KEY }));

    expect(await form.findByText(GONE)).toBeInTheDocument();
    expect(form.getByLabelText("Название")).toHaveValue("Поздний ужин");
  });

  it("shows the text once when a save finds the event gone too", async () => {
    const events = [makeEvent({ title: "Ужин" })];
    // The save waits until the test lets it fail, so the banners are read once it has failed.
    let letSaveFail: () => void = () => undefined;
    const saveFails = new Promise<void>((resolve) => {
      letSaveFail = resolve;
    });
    const calls = stubApp({
      events,
      onRequest: (request) =>
        request.method === "PATCH"
          ? saveFails.then(() => apiError(404, "not_found", "Не найдено"))
          : undefined,
    });
    const user = userEvent.setup();
    const { client } = renderApp(`${DAY}&event=e1&edit=1`);

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    events.length = 0;
    await act(() => client.invalidateQueries({ queryKey: CALENDAR_KEY }));
    expect(await form.findByText(GONE)).toBeInTheDocument();

    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Поздний ужин");
    const save = form.getByRole("button", { name: "Сохранить" });
    await user.click(save);
    await waitFor(() => expect(requestsTo(calls, "PATCH", EVENT)).toHaveLength(1));
    expect(save).toHaveAttribute("aria-busy");

    letSaveFail();
    await waitFor(() => expect(save).not.toHaveAttribute("aria-busy"));
    expect(form.getAllByText(GONE)).toHaveLength(1);
  });
});

describe("a link to a task that fails after the event is created", () => {
  it("closes the form, says the event exists, and posts the event once", async () => {
    const calls = stubApp({
      onRequest: (request) =>
        answering("POST", EVENTS, () => json(201, makeEvent({ id: "new" })))(request) ??
        answering("POST", TASK_LINKS, () => apiError(404, "not_found", "Не найдено"))(request),
    });
    const user = userEvent.setup();
    renderApp(`${DAY}&event=new&for_task=t1`);

    const form = within(await screen.findByRole("dialog", { name: "Новое событие" }));
    await user.type(form.getByLabelText("Название"), "Ужин");
    await user.click(form.getByRole("button", { name: "Создать" }));

    expect(
      await screen.findByText("Событие создано, но связать с задачей не удалось"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Новое событие" })).not.toBeInTheDocument(),
    );
    expect(requestsTo(calls, "POST", TASK_LINKS)).toHaveLength(1);
    expect(requestsTo(calls, "POST", EVENTS)).toHaveLength(1);
  });
});

describe("an unchanged time after a clock change", () => {
  it("saves a new title of an event whose end reads before its start", async () => {
    // New York turns its clocks back at 06:00 UTC on 1 November 2026: 01:45 before, 01:15 after.
    const event = makeEvent({
      title: "Ужин",
      start_at: "2026-11-01T05:45:00Z",
      end_at: "2026-11-01T06:15:00Z",
      version: 2,
    });
    const newYorker = { ...USER, timezone: "America/New_York" };
    const calls = stubApp({
      events: [event],
      onRequest: (request) =>
        answering("GET", `${API}/me`, () => json(200, newYorker))(request) ??
        answering("PATCH", EVENT, () => json(200, event))(request),
    });
    const user = userEvent.setup();
    renderApp("/calendar?day=2026-11-01&event=e1&edit=1");

    const form = within(await screen.findByRole("dialog", { name: "Изменить событие" }));
    expect(form.getByLabelText("Время начала")).toHaveValue("01:45");
    expect(form.getByLabelText("Время конца")).toHaveValue("01:15");
    await user.clear(form.getByLabelText("Название"));
    await user.type(form.getByLabelText("Название"), "Поздний ужин");
    await user.click(form.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(requestsTo(calls, "PATCH", EVENT)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", EVENT)[0]!)).toEqual({
      title: "Поздний ужин",
      version: 2,
    });
  });
});
