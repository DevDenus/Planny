import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  API,
  apiError,
  json,
  makeBoard,
  makeNotification,
  makeTask,
  path,
  renderApp,
  requestsTo,
  stubApp,
  type Stub,
} from "../tasks/testing";

const NOTIFICATIONS = `${API}/notifications`;
const READ_ALL = `${NOTIFICATIONS}/read-all`;

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

/** Marks a notification as read when the app asks for it. */
const READ: Stub = (request) =>
  request.method === "POST" && path(request).endsWith("/read")
    ? json(200, makeNotification())
    : undefined;

/** Opens the bell from the top bar, the mobile header has a second one. */
async function openBell(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  // The shell waits for the session before it shows the bell.
  const [bell] = await screen.findAllByRole("button", { name: "Уведомления" });
  await user.click(bell!);
  return screen.findByRole("dialog", { name: "Уведомления" });
}

describe("notifications", () => {
  it("opens the panel from the bell and shows the notification text", async () => {
    const personal = makeBoard({ is_default: true });
    stubApp({
      boards: [personal],
      notifications: [makeNotification({ kind: "task_assigned", title: "Купить хлеб" })],
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);

    expect(await within(panel).findByText("Вам назначена задача: Купить хлеб")).toBeInTheDocument();
  });

  it("sends POST read and opens the task when a task notification is clicked", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const notification = makeNotification({
      kind: "task_assigned",
      title: "Купить хлеб",
      task_id: task.id,
    });
    const calls = stubApp({
      boards: [personal],
      tasks: [task],
      notifications: [notification],
      onRequest: READ,
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);
    await user.click(await within(panel).findByText("Вам назначена задача: Купить хлеб"));

    expect(await screen.findByDisplayValue("Купить хлеб")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Задача" })).toBeInTheDocument();
    expect(requestsTo(calls, "POST", `${NOTIFICATIONS}/${notification.id}/read`)).toHaveLength(1);
  });

  it("marks every notification read with POST read-all", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({
      boards: [personal],
      notifications: [makeNotification({ title: "Купить хлеб" })],
      // The button is enabled by the unread count of the sync state, so the count must show it.
      sync: { calendar: 0, tasks: 0, notifications: 1, unread_notifications: 1 },
      onRequest: (request) =>
        request.method === "POST" && path(request) === READ_ALL
          ? new Response(null, { status: 204 })
          : undefined,
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);
    await user.click(await within(panel).findByRole("button", { name: "Прочитать всё" }));

    expect(requestsTo(calls, "POST", READ_ALL)).toHaveLength(1);
  });

  it("enables read-all when the count shows unread notifications on a page not loaded yet", async () => {
    const personal = makeBoard({ is_default: true });
    const read = makeNotification({ title: "Купить хлеб", read_at: new Date().toISOString() });
    stubApp({
      boards: [personal],
      sync: { calendar: 0, tasks: 0, notifications: 3, unread_notifications: 3 },
      onRequest: (request) =>
        request.method === "GET" && path(request) === NOTIFICATIONS
          ? json(200, { items: [read], next_cursor: "older" })
          : undefined,
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);

    expect(await within(panel).findByText("Вам назначена задача: Купить хлеб")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Прочитать всё" })).toBeEnabled();
  });

  it("disables read-all when nothing is unread", async () => {
    const personal = makeBoard({ is_default: true });
    stubApp({
      boards: [personal],
      notifications: [
        makeNotification({ title: "Купить хлеб", read_at: new Date().toISOString() }),
      ],
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);

    expect(await within(panel).findByText("Вам назначена задача: Купить хлеб")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Прочитать всё" })).toBeDisabled();
  });

  it("says the task no longer exists when the task of a notification is gone", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id });
    stubApp({
      boards: [personal],
      tasks: [task],
      notifications: [
        makeNotification({ kind: "task_assigned", title: "Купить хлеб", task_id: task.id }),
      ],
      onRequest: (request) => {
        if (request.method === "GET" && path(request) === `${API}/tasks/${task.id}`) {
          return apiError(404, "not_found", "Не найдено");
        }
        return READ(request);
      },
    });
    renderApp("/calendar");

    const user = userEvent.setup();
    const panel = await openBell(user);
    await user.click(await within(panel).findByText("Вам назначена задача: Купить хлеб"));

    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
  });
});
