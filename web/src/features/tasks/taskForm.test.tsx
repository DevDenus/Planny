import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Board, Task } from "../../api/client";
import { TASKS_KEY } from "../../api/queryClient";
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
  stubApp,
  USER,
  type Stub,
} from "./testing";

const TASKS = `${API}/tasks`;

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

/**
 * The form dialog, read only once its fields exist. Loading shows a skeleton dialog first and
 * then a different element, so a dialog found earlier would be detached by then.
 */
async function formDialog(name: "Задача" | "Новая задача"): Promise<HTMLElement> {
  await screen.findByRole("textbox", { name: "Название" });
  return screen.getByRole("dialog", { name });
}

function openTask(task: Task, options: { boards: Board[]; tasks?: Task[]; onRequest?: Stub }) {
  const calls = stubApp({
    boards: options.boards,
    tasks: options.tasks ?? [task],
    onRequest: options.onRequest,
  });
  return { calls, ...renderApp(`/tasks?task=${task.id}`) };
}

/** Answers every write with a success so the form can close. */
const SAVED: Stub = (request) => (request.method === "PATCH" ? json(200, makeTask()) : undefined);

const CREATED: Stub = (request) =>
  request.method === "POST" && new URL(request.url).pathname === TASKS
    ? json(201, makeTask())
    : undefined;

describe("new task", () => {
  it("asks for a title and sends nothing when the title is empty", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({ boards: [personal] });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await within(dialog).findByRole("textbox", { name: "Название" });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(await within(dialog).findByText("Введите название")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", TASKS)).toHaveLength(0);
  });

  it("sends POST /tasks for a valid form and closes the dialog", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({ boards: [personal], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Купить хлеб",
    );
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    const body = await bodyOf(post!);
    expect(body).toMatchObject({ title: "Купить хлеб", board_id: personal.id, priority: 3 });
    expect(body.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("sends due_at in UTC and no due_date when a deadline comes with a time", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(5);
    const calls = stubApp({ boards: [personal], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Оплатить счёт",
    );
    await user.type(within(dialog).getByLabelText("Дедлайн"), day);
    await user.type(within(dialog).getByLabelText("Время"), "18:00");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    // 18:00 in Moscow is 15:00 UTC.
    expect(await bodyOf(post!)).toMatchObject({
      due_date: null,
      due_at: `${day}T15:00:00Z`,
    });
  });

  it("sends due_date and no due_at when only a date is given", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(5);
    const calls = stubApp({ boards: [personal], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Сдать отчёт",
    );
    await user.type(within(dialog).getByLabelText("Дедлайн"), day);
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    expect(await bodyOf(post!)).toMatchObject({ due_date: day, due_at: null });
  });

  it("refuses a start date after the deadline", async () => {
    const personal = makeBoard({ is_default: true });
    const calls = stubApp({ boards: [personal], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(await within(dialog).findByRole("textbox", { name: "Название" }), "Ремонт");
    await user.type(within(dialog).getByLabelText("Дата начала"), dayFromToday(6));
    await user.type(within(dialog).getByLabelText("Дедлайн"), dayFromToday(5));
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(await within(dialog).findByText("Не позже дедлайна")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", TASKS)).toHaveLength(0);
  });

  it("sends the same id again when a failed save is repeated", async () => {
    const personal = makeBoard({ is_default: true });
    let posts = 0;
    const calls = stubApp({
      boards: [personal],
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== TASKS) return undefined;
        posts += 1;
        return posts === 1
          ? apiError(502, "upstream_unavailable", "Сервер не ответил")
          : json(201, makeTask());
      },
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Купить хлеб",
    );
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await within(dialog).findByText("Сервер не ответил")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [first, second] = await Promise.all(
      requestsTo(calls, "POST", TASKS).map((request) => bodyOf(request)),
    );
    expect(first!.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(second!.id).toBe(first!.id);
  });
});

describe("edit", () => {
  it("sends PATCH with the version and only the changed fields", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 4 });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить батон");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({ title: "Купить батон", version: 4 });
  });

  it("sends no PATCH and closes when nothing changed", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestsTo(calls, "PATCH", `${TASKS}/${task.id}`)).toHaveLength(0);
  });

  it("keeps the version and the fields it started from when the task refreshes underneath", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 4 });
    const tasks = [task];
    const { calls, client } = openTask(task, {
      boards: [personal],
      tasks,
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, makeTask({ ...task, version: 8 })) : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Приоритет" }), "1");

    // Someone else renames the task and bumps its version while the form is open.
    tasks.splice(0, 1, makeTask({ ...task, title: "Купить батон", version: 7 }));
    await act(async () => {
      await client.invalidateQueries({ queryKey: TASKS_KEY });
    });
    await waitFor(() => expect(requestsTo(calls, "GET", `${TASKS}/${task.id}`)).toHaveLength(2));
    expect(within(dialog).getByRole("textbox", { name: "Название" })).toHaveValue("Купить хлеб");

    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    // Only the priority is sent, with the version the form started from.
    expect(await bodyOf(patch!)).toEqual({ priority: 1, version: 4 });
  });

  it("shows the conflict, and repeats the save with the newer version on request", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 4 });
    const current = makeTask({ ...task, title: "Купить батон", version: 7 });
    let patches = 0;
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) => {
        if (request.method !== "PATCH") return undefined;
        patches += 1;
        return patches === 1
          ? apiError(409, "version_conflict", "Объект изменился", {
              current,
              last_change: { actor: { display_name: "Женя" }, at: new Date().toISOString() },
            })
          : json(200, current);
      },
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить молоко");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const conflict = await screen.findByRole("dialog", {
      name: "Объект изменился, пока вы его редактировали",
    });
    expect(within(conflict).getByText(/Женя/)).toBeInTheDocument();

    await user.click(within(conflict).getByRole("button", { name: "Сохранить мои изменения" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const patchesSent = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(patchesSent).toHaveLength(2);
    expect(await bodyOf(patchesSent[1]!)).toEqual({ title: "Купить молоко", version: 7 });
  });

  it("closes only the conflict dialog on Esc and keeps the typed text", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 4 });
    const current = makeTask({ ...task, title: "Купить батон", version: 7 });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        request.method === "PATCH"
          ? apiError(409, "version_conflict", "Объект изменился", {
              current,
              last_change: null,
            })
          : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить молоко");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    await screen.findByRole("dialog", { name: "Объект изменился, пока вы его редактировали" });

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Объект изменился, пока вы его редактировали" }),
      ).not.toBeInTheDocument(),
    );
    const form = screen.getByRole("dialog", { name: "Задача" });
    expect(within(form).getByRole("textbox", { name: "Название" })).toHaveValue("Купить молоко");
    expect(requestsTo(calls, "PATCH", `${TASKS}/${task.id}`)).toHaveLength(1);
  });

  it("offers to create the task again when it was deleted meanwhile", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 4 });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        request.method === "PATCH" ? apiError(404, "not_found", "Не найдено") : CREATED(request),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить батон");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(
      await within(dialog).findByText("Задачу удалили, пока вы её редактировали."),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Создать заново" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    expect(await bodyOf(post!)).toMatchObject({ title: "Купить батон", board_id: personal.id });
  });

  it("keeps the texts of the saved checklist when the task is created again", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      checklist: [
        { id: "c1", text: "Молоко", is_done: true, position: "a" },
        { id: "c2", text: "Яйца", is_done: false, position: "b" },
      ],
    });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        request.method === "PATCH" ? apiError(404, "not_found", "Не найдено") : CREATED(request),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить батон");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(
      await within(dialog).findByText("Задачу удалили, пока вы её редактировали."),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Создать заново" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    expect(await bodyOf(post!)).toMatchObject({
      title: "Купить батон",
      checklist: ["Молоко", "Яйца"],
    });
  });

  it("says the task is gone when it is opened again after it was deleted", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    let gone = false;
    openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        gone && request.method === "GET" && path(request) === `${TASKS}/${task.id}`
          ? apiError(404, "not_found", "Не найдено")
          : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    // Deleted while the form was closed. Opening it again must not show the cached copy.
    gone = true;
    await user.click(await screen.findByText("Купить хлеб"));

    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Название" })).not.toBeInTheDocument();
  });

  it("offers the assignee checkbox on a board of one member, so the owner can take the task", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", version: 2 });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(await within(dialog).findByRole("checkbox", { name: USER.display_name }));
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({ assignee_ids: [USER.id], version: 2 });
  });

  it("says the task no longer exists when opening it answers 404", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id });
    openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        request.method === "GET" && path(request) === `${TASKS}/${task.id}`
          ? apiError(404, "not_found", "Не найдено")
          : undefined,
    });

    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
  });

  it("locks the fields and hides the save button for a viewer of the board", async () => {
    const shared = makeBoard({ is_shared: true, my_role: "viewer", name: "Общая" });
    const task = makeTask({ board_id: shared.id, title: "Купить хлеб" });
    openTask(task, { boards: [shared] });

    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    // The board decides the lock, so it can arrive a moment after the task.
    await waitFor(() =>
      expect(within(dialog).getByRole("textbox", { name: "Название" })).toBeDisabled(),
    );
    expect(within(dialog).queryByRole("button", { name: "Сохранить" })).not.toBeInTheDocument();
  });

  it("sends the new state of a checklist item when it is ticked", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({
      board_id: personal.id,
      checklist: [{ id: "c1", text: "Молоко", is_done: false, position: "a" }],
    });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) => (request.method === "PATCH" ? json(200, {}) : undefined),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await user.click(await within(dialog).findByRole("checkbox", { name: "Молоко" }));

    const url = `${TASKS}/${task.id}/checklist/c1`;
    await waitFor(() => expect(requestsTo(calls, "PATCH", url)).toHaveLength(1));
    const [patch] = requestsTo(calls, "PATCH", url);
    expect(await bodyOf(patch!)).toEqual({ is_done: true });
  });

  it("adds a checklist item on Enter", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) => (request.method === "POST" ? json(201, {}) : undefined),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await user.type(await within(dialog).findByLabelText("Новый пункт"), "Яйца{Enter}");

    const url = `${TASKS}/${task.id}/checklist`;
    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(1));
    const [post] = requestsTo(calls, "POST", url);
    expect(await bodyOf(post!)).toEqual({ text: "Яйца" });
  });

  it("asks for confirmation before deleting and sends DELETE only once confirmed", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        request.method === "DELETE" ? new Response(null, { status: 204 }) : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    const confirm = await screen.findByRole("dialog", { name: "Удалить задачу?" });
    expect(requestsTo(calls, "DELETE", `${TASKS}/${task.id}`)).toHaveLength(0);

    await user.click(within(confirm).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestsTo(calls, "DELETE", `${TASKS}/${task.id}`)).toHaveLength(1);
  });

  it("keeps the form open and sends nothing when the deletion is cancelled", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const { calls } = openTask(task, { boards: [personal] });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    const confirm = await screen.findByRole("dialog", { name: "Удалить задачу?" });
    await user.click(within(confirm).getByRole("button", { name: "Отмена" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Удалить задачу?" })).not.toBeInTheDocument(),
    );
    const form = screen.getByRole("dialog", { name: "Задача" });
    expect(within(form).getByRole("textbox", { name: "Название" })).toHaveValue("Купить хлеб");
    expect(requestsTo(calls, "DELETE", `${TASKS}/${task.id}`)).toHaveLength(0);
  });
});
