import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SyncState } from "../../api/client";
import {
  API,
  apiError,
  makeBoard,
  makeNotification,
  makeTask,
  path,
  renderApp,
  requestsTo,
  stubApp,
} from "../tasks/testing";

const TASKS = `${API}/tasks`;
const NOTIFICATIONS = `${API}/notifications`;
const SYNC = `${API}/sync`;

function quietSync(): SyncState {
  return { calendar: 0, tasks: 0, notifications: 0, unread_notifications: 0 };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

afterEach(() => {
  vi.useRealTimers();
});

/** One polling interval of the sync counters: the screens poll every 5 seconds. */
async function oneInterval() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
}

describe("sync", () => {
  it("refetches the visible list when the tasks counter grows, without a reload", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const personal = makeBoard({ is_default: true });
    const tasks = [makeTask({ board_id: personal.id, title: "Купить хлеб" })];
    const sync = quietSync();
    const calls = stubApp({ boards: [personal], tasks, sync });
    renderApp("/tasks");
    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    const listsBefore = requestsTo(calls, "GET", TASKS).length;

    // Another device adds a task and bumps the counter.
    tasks.push(makeTask({ board_id: personal.id, title: "Молоко" }));
    sync.tasks += 1;
    await oneInterval();

    expect(await screen.findByText("Молоко")).toBeInTheDocument();
    expect(requestsTo(calls, "GET", TASKS).length).toBeGreaterThan(listsBefore);
  });

  it("marks the notifications stale when their counter grows, so an open panel refetches", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const personal = makeBoard({ is_default: true });
    const notifications = [makeNotification({ title: "Купить хлеб" })];
    const sync = quietSync();
    const calls = stubApp({ boards: [personal], notifications, sync });
    renderApp("/calendar");
    expect(await screen.findByRole("heading", { name: "Календарь" })).toBeInTheDocument();

    const user = userEvent.setup({ delay: null });
    const [bell] = screen.getAllByRole("button", { name: "Уведомления" });
    await user.click(bell!);
    expect(await screen.findByText("Вам назначена задача: Купить хлеб")).toBeInTheDocument();
    expect(requestsTo(calls, "GET", NOTIFICATIONS)).toHaveLength(1);

    notifications.push(makeNotification({ title: "Молоко" }));
    sync.notifications += 1;
    await oneInterval();

    await waitFor(() => expect(requestsTo(calls, "GET", NOTIFICATIONS)).toHaveLength(2));
    expect(await screen.findByText("Вам назначена задача: Молоко")).toBeInTheDocument();
  });

  it("shows the unread count as a badge on the bell", async () => {
    const personal = makeBoard({ is_default: true });
    stubApp({
      boards: [personal],
      sync: { ...quietSync(), unread_notifications: 3 },
    });
    renderApp("/calendar");

    // The bell is in the top bar and in the mobile header.
    await waitFor(() => {
      const bells = screen.getAllByRole("button", { name: "Уведомления" });
      expect(bells).toHaveLength(2);
      for (const bell of bells) expect(bell).toHaveTextContent("3");
    });
  });

  it("says the connection is lost when the sync request fails", async () => {
    const personal = makeBoard({ is_default: true });
    stubApp({
      boards: [personal],
      onRequest: (request) =>
        path(request) === SYNC ? apiError(500, "internal", "Сбой сервера") : undefined,
    });
    renderApp("/calendar");

    expect(await screen.findByText("Нет связи с сервером")).toBeInTheDocument();
  });
});
