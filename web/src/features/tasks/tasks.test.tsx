import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  API,
  apiError,
  bodyOf,
  dayFromToday,
  json,
  makeBoard,
  makeTask,
  path,
  renderApp,
  requestsTo,
  searchOf,
  stubApp,
} from "./testing";

const TASKS = `${API}/tasks`;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

/** A response the test gives later, so the screen can be seen while the request is open. */
function deferred() {
  let answer!: (response: Response) => void;
  const response = new Promise<Response>((resolve) => {
    answer = resolve;
  });
  return { response, answer };
}

/** The panel of one task group, found from its heading. */
function groupOf(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("button")!.parentElement!;
}

/** The query of the most recent list request. */
function lastList(calls: Request[]): URLSearchParams {
  return searchOf(requestsTo(calls, "GET", TASKS).at(-1)!);
}

describe("task list", () => {
  it("groups the open tasks by their deadline", async () => {
    const personal = makeBoard({ is_default: true });
    const tasks = [
      makeTask({ board_id: personal.id, title: "Старое дело", due_date: dayFromToday(-3) }),
      makeTask({ board_id: personal.id, title: "Срочное дело", due_date: dayFromToday(0) }),
      makeTask({ board_id: personal.id, title: "Дальнее дело", due_date: dayFromToday(30) }),
      makeTask({ board_id: personal.id, title: "Когда-нибудь" }),
    ];
    stubApp({ boards: [personal], tasks });
    renderApp("/tasks");

    await screen.findByText("Старое дело");
    expect(within(groupOf("Просрочено")).getByText("Старое дело")).toBeInTheDocument();
    expect(within(groupOf("Сегодня")).getByText("Срочное дело")).toBeInTheDocument();
    expect(within(groupOf("Позже")).getByText("Дальнее дело")).toBeInTheDocument();
    expect(within(groupOf("Без срока")).getByText("Когда-нибудь")).toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((item) => item.textContent);
    expect(headings.filter((title) => title !== "Выполненные" && title !== "Мои доски")).toEqual([
      "Просрочено",
      "Сегодня",
      "Позже",
      "Без срока",
    ]);
  });

  it("shows the empty state when there are no tasks", async () => {
    stubApp({ boards: [makeBoard({ is_default: true })] });
    renderApp("/tasks");

    expect(await screen.findByText("Задач нет. Добавьте первую")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Сегодня" })).not.toBeInTheDocument();
  });

  it("offers a retry when the list fails to load, and the retry loads it", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    let failOnce = true;
    const calls = stubApp({
      boards: [personal],
      tasks: [task],
      onRequest: (request) => {
        if (request.method === "GET" && path(request) === TASKS && failOnce) {
          failOnce = false;
          return apiError(500, "internal", "Ошибка сервера");
        }
        return undefined;
      },
    });
    renderApp("/tasks");

    expect(await screen.findByText("Не удалось загрузить задачи")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(requestsTo(calls, "GET", TASKS)).toHaveLength(2);
  });

  it("checks the box at once and sends POST /tasks/{id}/complete", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const tasks = [task];
    const answer = deferred();
    const calls = stubApp({
      boards: [personal],
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${task.id}/complete`
          ? answer.response
          : undefined,
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const box = await screen.findByRole("checkbox", { name: "Выполнить: Купить хлеб" });
    await user.click(box);

    // The answer has not come yet, the box is already checked.
    await waitFor(() => expect(box).toBeChecked());
    expect(requestsTo(calls, "POST", `${TASKS}/${task.id}/complete`)).toHaveLength(1);

    tasks.splice(0, 1, { ...task, completed_at: new Date().toISOString() });
    answer.answer(json(200, tasks[0]));
    await waitFor(() => expect(screen.queryByText("Купить хлеб")).not.toBeInTheDocument());
  });

  it("returns the box to unchecked and shows the error when completing fails", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const answer = deferred();
    stubApp({
      boards: [personal],
      tasks: [task],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${task.id}/complete`
          ? answer.response
          : undefined,
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const box = await screen.findByRole("checkbox", { name: "Выполнить: Купить хлеб" });
    await user.click(box);
    await waitFor(() => expect(box).toBeChecked());

    answer.answer(apiError(500, "internal", "Не удалось отметить задачу"));

    expect(await screen.findByText("Не удалось отметить задачу")).toBeInTheDocument();
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("adds the row at once with a client id and clears the input", async () => {
    const personal = makeBoard({ is_default: true });
    const answer = deferred();
    const calls = stubApp({
      boards: [personal],
      onRequest: (request) =>
        request.method === "POST" && path(request) === TASKS ? answer.response : undefined,
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "Быстро добавить задачу" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Молоко{Enter}");

    expect(await screen.findByText("Молоко")).toBeInTheDocument();
    expect(input).toHaveValue("");
    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(1));
    const [post] = requestsTo(calls, "POST", TASKS);
    const body = await bodyOf(post!);
    expect(body).toMatchObject({ title: "Молоко", board_id: personal.id, priority: 3 });
    expect(body.id).toMatch(UUID);

    answer.answer(json(201, makeTask({ id: body.id as string, board_id: personal.id })));
    await waitFor(() => expect(requestsTo(calls, "GET", TASKS).length).toBeGreaterThan(1));
  });

  it("removes the row and shows the error when adding fails", async () => {
    const personal = makeBoard({ is_default: true });
    const answer = deferred();
    stubApp({
      boards: [personal],
      onRequest: (request) =>
        request.method === "POST" && path(request) === TASKS ? answer.response : undefined,
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "Быстро добавить задачу" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Молоко{Enter}");
    expect(await screen.findByText("Молоко")).toBeInTheDocument();

    answer.answer(apiError(500, "internal", "Не удалось создать задачу"));

    expect(await screen.findByText("Не удалось создать задачу")).toBeInTheDocument();
    expect(screen.queryByText("Молоко")).not.toBeInTheDocument();
  });

  it("puts the text of a failed add back, and sending it again keeps the id", async () => {
    const personal = makeBoard({ is_default: true });
    let posts = 0;
    const calls = stubApp({
      boards: [personal],
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== TASKS) return undefined;
        posts += 1;
        return posts === 1
          ? apiError(500, "internal", "Не удалось создать задачу")
          : json(201, makeTask({ board_id: personal.id, title: "Молоко" }));
      },
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "Быстро добавить задачу" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Молоко{Enter}");
    expect(await screen.findByText("Не удалось создать задачу")).toBeInTheDocument();
    expect(input).toHaveValue("Молоко");

    await user.click(input);
    await user.keyboard("{Enter}");

    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(2));
    const [first, second] = await Promise.all(
      requestsTo(calls, "POST", TASKS).map((request) => bodyOf(request)),
    );
    expect(first!.id).toMatch(UUID);
    expect(second!.id).toBe(first!.id);
    expect(second).toMatchObject({ title: "Молоко" });
  });

  it("sends a new id when the text was changed before it is sent again", async () => {
    const personal = makeBoard({ is_default: true });
    let posts = 0;
    const calls = stubApp({
      boards: [personal],
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== TASKS) return undefined;
        posts += 1;
        return posts === 1
          ? apiError(500, "internal", "Не удалось создать задачу")
          : json(201, makeTask({ board_id: personal.id, title: "Хлеб" }));
      },
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "Быстро добавить задачу" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Молоко{Enter}");
    expect(await screen.findByText("Не удалось создать задачу")).toBeInTheDocument();
    expect(input).toHaveValue("Молоко");

    await user.clear(input);
    await user.type(input, "Хлеб{Enter}");

    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(2));
    const [first, second] = await Promise.all(
      requestsTo(calls, "POST", TASKS).map((request) => bodyOf(request)),
    );
    expect(second).toMatchObject({ title: "Хлеб" });
    expect(second!.id).not.toBe(first!.id);
  });

  it("leaves the text typed meanwhile alone when an earlier add fails", async () => {
    const personal = makeBoard({ is_default: true });
    const answer = deferred();
    const calls = stubApp({
      boards: [personal],
      onRequest: (request) =>
        request.method === "POST" && path(request) === TASKS ? answer.response : undefined,
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    const input = await screen.findByRole("textbox", { name: "Быстро добавить задачу" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Молоко{Enter}");
    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(1));
    await user.type(input, "Хлеб");

    answer.answer(apiError(500, "internal", "Не удалось создать задачу"));

    expect(await screen.findByText("Не удалось создать задачу")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Молоко")).not.toBeInTheDocument());
    expect(input).toHaveValue("Хлеб");
    expect(requestsTo(calls, "POST", TASKS)).toHaveLength(1);
  });

  it("refetches with assignee=me when the assigned-to-me switch is turned on", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({ boards: [personal] });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("switch", { name: "Назначенные мне" }));

    await waitFor(() => expect(lastList(calls).get("assignee")).toBe("me"));
  });

  it("refetches with scope=personal when the personal segment is chosen", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({ boards: [personal] });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Личные" }));

    await waitFor(() => expect(lastList(calls).get("scope")).toBe("personal"));
  });

  it("opens the task dialog with the title when a row is clicked", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    stubApp({ boards: [personal], tasks: [task] });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByText("Купить хлеб"));

    expect(await screen.findByDisplayValue("Купить хлеб")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Задача" })).toBeInTheDocument();
  });
});

describe("groups follow the clock", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("moves a task from Сегодня to Просрочено once its time has passed, without refetching", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // 12:00 in Moscow, the deadline is two minutes ahead.
    vi.setSystemTime(new Date("2030-01-10T09:00:00Z"));
    const personal = makeBoard({ is_default: true });
    const task = makeTask({
      board_id: personal.id,
      title: "Созвон",
      due_at: "2030-01-10T09:02:00Z",
    });
    const calls = stubApp({ boards: [personal], tasks: [task] });
    renderApp("/tasks");

    expect(await screen.findByText("Созвон")).toBeInTheDocument();
    expect(within(groupOf("Сегодня")).getByText("Созвон")).toBeInTheDocument();
    const listRequests = requestsTo(calls, "GET", TASKS).length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3 * 60_000);
    });

    expect(within(groupOf("Просрочено")).getByText("Созвон")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Сегодня" })).not.toBeInTheDocument();
    expect(requestsTo(calls, "GET", TASKS)).toHaveLength(listRequests);
  });

  it("moves a task due tomorrow into Сегодня after midnight", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // 23:59:30 in Moscow, on a Thursday, so tomorrow is still this week.
    vi.setSystemTime(new Date("2030-01-10T20:59:30Z"));
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Отчёт", due_date: "2030-01-11" });
    const calls = stubApp({ boards: [personal], tasks: [task] });
    renderApp("/tasks");

    expect(await screen.findByText("Отчёт")).toBeInTheDocument();
    expect(within(groupOf("На этой неделе")).getByText("Отчёт")).toBeInTheDocument();
    const listRequests = requestsTo(calls, "GET", TASKS).length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60_000);
    });

    expect(within(groupOf("Сегодня")).getByText("Отчёт")).toBeInTheDocument();
    expect(requestsTo(calls, "GET", TASKS)).toHaveLength(listRequests);
  });
});
