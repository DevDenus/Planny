import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Board,
  BoardColumn,
  Label,
  Task,
  TaskActivity,
  TaskComment,
  UserSummary,
} from "../../api/client";
import { TASKS_KEY } from "../../api/queryClient";
import {
  API,
  apiError,
  bodyOf,
  dayFromToday,
  json,
  makeBoard,
  makeColumn,
  makeLabel,
  makeTask,
  path,
  renderApp,
  requestsTo,
  stubApp,
  USER,
  USER_SUMMARY,
  type Stub,
} from "./testing";

const TASKS = `${API}/tasks`;
const BOARDS = `${API}/boards`;
const ZHENYA: UserSummary = { id: "u2", display_name: "Женя", color: "pink" };

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

function openTask(
  task: Task,
  options: {
    boards: Board[];
    tasks?: Task[];
    onRequest?: Stub;
    columns?: BoardColumn[];
    labels?: Label[];
    comments?: TaskComment[];
    activity?: TaskActivity[];
  },
) {
  const calls = stubApp({
    boards: options.boards,
    tasks: options.tasks ?? [task],
    onRequest: options.onRequest,
    columns: options.columns,
    labels: options.labels,
    comments: options.comments,
    activity: options.activity,
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

  it("says the task was removed when a refresh answers 404, and keeps the typed text", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    let gone = false;
    const { calls, client } = openTask(task, {
      boards: [personal],
      onRequest: (request) =>
        gone && request.method === "GET" && path(request) === `${TASKS}/${task.id}`
          ? apiError(404, "not_found", "Не найдено")
          : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить батон");

    // Deleted meanwhile: the refetch fails, and the form keeps the copy it has.
    gone = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: TASKS_KEY });
    });
    await waitFor(() => expect(requestsTo(calls, "GET", `${TASKS}/${task.id}`)).toHaveLength(2));

    expect(
      await within(dialog).findByText("Задачу удалили, пока вы её редактировали."),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "Название" })).toHaveValue("Купить батон");
    expect(within(dialog).getByRole("button", { name: "Создать заново" })).toBeInTheDocument();
  });

  it("says the task was removed to a viewer, without a button to create it again", async () => {
    const shared = makeBoard({ is_shared: true, my_role: "viewer", name: "Общая" });
    const task = makeTask({ board_id: shared.id, title: "Купить хлеб" });
    let gone = false;
    const { client } = openTask(task, {
      boards: [shared],
      onRequest: (request) =>
        gone && request.method === "GET" && path(request) === `${TASKS}/${task.id}`
          ? apiError(404, "not_found", "Не найдено")
          : undefined,
    });

    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    // The board decides the lock, so it can arrive a moment after the task.
    await waitFor(() =>
      expect(within(dialog).getByRole("textbox", { name: "Название" })).toBeDisabled(),
    );

    gone = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: TASKS_KEY });
    });

    expect(
      await within(dialog).findByText("Задачу удалили, пока вы её редактировали."),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "Создать заново" }),
    ).not.toBeInTheDocument();
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

/** A comment as the server lists it. */
function commentOf(author: UserSummary, body: string, edited = false): TaskComment {
  const now = new Date().toISOString();
  return { id: crypto.randomUUID(), author, body, created_at: now, edited_at: edited ? now : null };
}

/** Answers the creation of a label on the board, and lists the label as the board does after it. */
function creatingLabels(boardId: string, labels: Label[]): Stub {
  return (request) => {
    if (request.method !== "POST" || path(request) !== `${BOARDS}/${boardId}/labels`) {
      return CREATED(request);
    }
    return bodyOf<{ name: string }>(request).then((body) => {
      const label = makeLabel({ name: body.name });
      labels.push(label);
      return json(201, label);
    });
  };
}

describe("labels", () => {
  it("sends the chosen labels with a new task", async () => {
    const personal = makeBoard({ is_default: true });
    const urgent = makeLabel({ name: "Срочно" });
    const calls = stubApp({ boards: [personal], labels: [urgent], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Купить хлеб",
    );
    await user.click(await within(dialog).findByRole("checkbox", { name: "Срочно" }));
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    expect(await bodyOf(post!)).toMatchObject({ label_ids: [urgent.id] });
  });

  it("creates a label from the picker and ticks it", async () => {
    const personal = makeBoard({ is_default: true });
    const labels: Label[] = [];
    const calls = stubApp({
      boards: [personal],
      labels,
      onRequest: creatingLabels(personal.id, labels),
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.click(await within(dialog).findByRole("button", { name: "Новая метка" }));
    await user.type(within(dialog).getByRole("textbox", { name: "Название метки" }), "Важно");
    await user.click(within(dialog).getByRole("button", { name: "Добавить метку" }));

    expect(await within(dialog).findByRole("checkbox", { name: "Важно" })).toBeChecked();
    const [post] = requestsTo(calls, "POST", `${BOARDS}/${personal.id}/labels`);
    expect(await bodyOf(post!)).toEqual({ name: "Важно", color: "blue" });
  });

  it("does not submit the task when Enter is pressed in the new label's name", async () => {
    const personal = makeBoard({ is_default: true });
    const labels: Label[] = [];
    const calls = stubApp({
      boards: [personal],
      labels,
      onRequest: creatingLabels(personal.id, labels),
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.click(await within(dialog).findByRole("button", { name: "Новая метка" }));
    const name = within(dialog).getByRole("textbox", { name: "Название метки" });
    await user.type(name, "Важно");
    // A browser would submit the task form on Enter, unless the key press is cancelled. fireEvent
    // reports false only for a cancelled key press, and user-event does not simulate that submit.
    expect(fireEvent.keyDown(name, { key: "Enter" })).toBe(false);

    // Enter adds the label, and only that: the task form stays as it was.
    await waitFor(() =>
      expect(requestsTo(calls, "POST", `${BOARDS}/${personal.id}/labels`)).toHaveLength(1),
    );
    expect(requestsTo(calls, "POST", TASKS)).toHaveLength(0);
    expect(screen.getByRole("dialog", { name: "Новая задача" })).toBeInTheDocument();
  });

  it("sends the changed labels with the version", async () => {
    const personal = makeBoard({ is_default: true });
    const urgent = makeLabel({ name: "Срочно" });
    const errands = makeLabel({ name: "Покупки" });
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      labels: [urgent],
    });
    const { calls } = openTask(task, {
      boards: [personal],
      labels: [urgent, errands],
      onRequest: SAVED,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(await within(dialog).findByRole("checkbox", { name: "Покупки" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Срочно" }));
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({ label_ids: [errands.id], version: 4 });
  });

  it("does not send the labels when they were not changed", async () => {
    const personal = makeBoard({ is_default: true });
    const urgent = makeLabel({ name: "Срочно" });
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      labels: [urgent],
    });
    const { calls } = openTask(task, {
      boards: [personal],
      labels: [urgent],
      onRequest: SAVED,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await within(dialog).findByRole("checkbox", { name: "Срочно" });
    await user.clear(title);
    await user.type(title, "Купить батон");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({ title: "Купить батон", version: 4 });
  });
});

describe("reminder", () => {
  it("shows the personal reminder in the user's zone", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(4);
    // 06:00 UTC is 09:00 in Moscow.
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      reminder_at: `${day}T06:00:00Z`,
    });
    openTask(task, { boards: [personal] });

    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    expect(within(dialog).getByLabelText("Напоминание")).toHaveValue(day);
    expect(within(dialog).getByLabelText("Время напоминания")).toHaveValue("09:00");
  });

  it("sets the reminder to 09:00 on the day of the deadline", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(5);
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      due_date: day,
    });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "В день срока в 09:00" }));

    expect(within(dialog).getByLabelText("Напоминание")).toHaveValue(day);
    expect(within(dialog).getByLabelText("Время напоминания")).toHaveValue("09:00");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    // 09:00 in Moscow is 06:00 UTC. The deadline is unchanged, so it is not sent.
    expect(await bodyOf(patch!)).toEqual({ reminder_at: `${day}T06:00:00Z`, version: 4 });
  });

  it("sets the reminder to 09:00 the day before the deadline", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      due_date: dayFromToday(5),
    });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "За день в 09:00" }));

    expect(within(dialog).getByLabelText("Напоминание")).toHaveValue(dayFromToday(4));
    expect(within(dialog).getByLabelText("Время напоминания")).toHaveValue("09:00");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({
      reminder_at: `${dayFromToday(4)}T06:00:00Z`,
      version: 4,
    });
  });

  it("disables the quick reminders until the task has a deadline", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    openTask(task, { boards: [personal] });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    expect(within(dialog).getByRole("button", { name: "В день срока в 09:00" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "За день в 09:00" })).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Дедлайн"), dayFromToday(5));
    expect(within(dialog).getByRole("button", { name: "В день срока в 09:00" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "За день в 09:00" })).toBeEnabled();
  });

  it("clears the reminder and sends reminder_at as null", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(5);
    const task = makeTask({
      board_id: personal.id,
      title: "Купить хлеб",
      version: 4,
      due_date: day,
      reminder_at: `${day}T06:00:00Z`,
    });
    const { calls } = openTask(task, { boards: [personal], onRequest: SAVED });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.click(within(dialog).getByRole("button", { name: "Без напоминания" }));

    expect(within(dialog).getByLabelText("Напоминание")).toHaveValue("");
    expect(within(dialog).getByLabelText("Время напоминания")).toHaveValue("");
    expect(
      within(dialog).queryByRole("button", { name: "Без напоминания" }),
    ).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = requestsTo(calls, "PATCH", `${TASKS}/${task.id}`);
    expect(await bodyOf(patch!)).toEqual({ reminder_at: null, version: 4 });
  });

  it("asks for the time next to a reminder date, and sends nothing", async () => {
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
    await user.type(within(dialog).getByLabelText("Напоминание"), dayFromToday(5));
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(await within(dialog).findByText("Укажите дату и время")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", TASKS)).toHaveLength(0);
  });

  it("sends the reminder as an instant with a new task", async () => {
    const personal = makeBoard({ is_default: true });
    const day = dayFromToday(5);
    const calls = stubApp({ boards: [personal], onRequest: CREATED });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая задача" }));
    const dialog = await formDialog("Новая задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Название" }),
      "Купить хлеб",
    );
    await user.type(within(dialog).getByLabelText("Напоминание"), day);
    await user.type(within(dialog).getByLabelText("Время напоминания"), "18:00");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [post] = requestsTo(calls, "POST", TASKS);
    // 18:00 in Moscow is 15:00 UTC.
    expect(await bodyOf(post!)).toMatchObject({ reminder_at: `${day}T15:00:00Z` });
  });
});

describe("moving to another board", () => {
  /** A card with a label on the personal board, and a second board to send it to. */
  function boardsWithCard() {
    const personal = makeBoard({ is_default: true, name: "Личная" });
    const family = makeBoard({ name: "Семья", is_shared: true, members: [USER_SUMMARY, ZHENYA] });
    const todo = makeColumn({ name: "К выполнению", position: "a" });
    const done = makeColumn({ name: "Готово", position: "b", is_done: true });
    const arrival = makeColumn({ name: "Новые", position: "a" });
    const urgent = makeLabel({ name: "Срочно" });
    const task = makeTask({
      board_id: personal.id,
      column_id: todo.id,
      title: "Купить хлеб",
      version: 4,
      labels: [urgent],
    });
    const familyColumns: Stub = (request) =>
      path(request) === `${BOARDS}/${family.id}/columns`
        ? json(200, { items: [arrival] })
        : undefined;
    return { personal, family, todo, done, arrival, urgent, task, familyColumns };
  }

  it("sends the changes and the move in one request, to the first open column", async () => {
    const { personal, family, todo, done, arrival, urgent, task, familyColumns } = boardsWithCard();
    const { calls } = openTask(task, {
      boards: [personal, family],
      columns: [todo, done],
      labels: [urgent],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${task.id}/move`
          ? json(200, makeTask({ ...task, board_id: family.id, labels: [], version: 5 }))
          : familyColumns(request),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const title = await within(dialog).findByDisplayValue("Купить хлеб");
    await user.clear(title);
    await user.type(title, "Купить батон");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Доска" }), family.id);

    expect(
      within(dialog).getByText(
        "Метки сбросятся, а исполнители, которых нет на новой доске, будут сняты",
      ),
    ).toBeInTheDocument();
    // The columns of the new board load after the change, and the first open one is then listed.
    await within(dialog).findByRole("option", { name: "Новые" });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const moves = requestsTo(calls, "POST", `${TASKS}/${task.id}/move`);
    expect(requestsTo(calls, "PATCH", `${TASKS}/${task.id}`)).toHaveLength(0);
    expect(moves).toHaveLength(1);
    expect(await bodyOf(moves[0]!)).toEqual({
      column_id: arrival.id,
      after_id: null,
      changes: { title: "Купить батон", label_ids: [], version: 4 },
    });
  });

  it("sends no changes with a move when only the column is new", async () => {
    const { personal, todo, done, task: labeled } = boardsWithCard();
    const task = { ...labeled, labels: [] };
    const { calls } = openTask(task, {
      boards: [personal],
      columns: [todo, done],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${task.id}/move`
          ? json(200, makeTask({ ...task, column_id: done.id }))
          : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await within(dialog).findByRole("option", { name: "Готово" });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Колонка" }), done.id);
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [sent] = requestsTo(calls, "POST", `${TASKS}/${task.id}/move`);
    expect(await bodyOf(sent!)).toEqual({ column_id: done.id, after_id: null });
  });

  it("shows the conflict when a move with changes finds a newer card", async () => {
    const { personal, family, todo, done, urgent, task, familyColumns } = boardsWithCard();
    openTask(task, {
      boards: [personal, family],
      columns: [todo, done],
      labels: [urgent],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${task.id}/move`
          ? apiError(409, "version_conflict", "Конфликт", {
              current: { ...task, version: 5 },
              last_change: null,
            })
          : familyColumns(request),
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Доска" }), family.id);
    await within(dialog).findByRole("option", { name: "Новые" });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    expect(
      await screen.findByRole("dialog", { name: "Объект изменился, пока вы его редактировали" }),
    ).toBeInTheDocument();
  });

  it("offers a retry and doesn't save while the columns of the new board can't be loaded", async () => {
    const { personal, family, todo, done, urgent, task } = boardsWithCard();
    let broken = true;
    openTask(task, {
      boards: [personal, family],
      columns: [todo, done],
      labels: [urgent],
      onRequest: (request) =>
        broken && path(request) === `${BOARDS}/${family.id}/columns`
          ? apiError(404, "not_found", "Не найдено")
          : undefined,
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await within(dialog).findByDisplayValue("Купить хлеб");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Доска" }), family.id);

    expect(
      await within(dialog).findByText("Не удалось загрузить колонки доски"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Сохранить" })).toBeDisabled();

    broken = false;
    await user.click(within(dialog).getByRole("button", { name: "Повторить" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Сохранить" })).toBeEnabled(),
    );
  });
});

describe("comments and history", () => {
  it("lists the comments and marks an edited one", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", comments_count: 2 });
    openTask(task, {
      boards: [personal],
      comments: [commentOf(ZHENYA, "Возьми батон"), commentOf(USER_SUMMARY, "Хорошо", true)],
    });

    const dialog = await formDialog("Задача");
    const feed = await within(dialog).findByRole("region", { name: "Комментарии и история" });
    expect(await within(feed).findByText("Возьми батон")).toBeInTheDocument();
    expect(within(feed).getByText("Хорошо")).toBeInTheDocument();
    expect(within(feed).getAllByText("изменено")).toHaveLength(1);
  });

  it("opens the editor with the text a comment has now, after it changed while shown", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб", comments_count: 1 });
    const comments = [commentOf(USER_SUMMARY, "Хорошо")];
    const { client } = openTask(task, { boards: [personal], comments });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    const feed = await within(dialog).findByRole("region", { name: "Комментарии и история" });
    await within(feed).findByText("Хорошо");

    // Someone else changes the text, and the feed loads it again.
    comments.splice(0, 1, { ...comments[0]!, body: "Хорошо, беру батон" });
    await act(async () => {
      await client.invalidateQueries({ queryKey: [...TASKS_KEY, "comments"] });
    });
    expect(await within(feed).findByText("Хорошо, беру батон")).toBeInTheDocument();

    await user.click(within(feed).getByRole("button", { name: "Изменить" }));

    expect(within(feed).getByRole("textbox", { name: "Текст комментария" })).toHaveValue(
      "Хорошо, беру батон",
    );
  });

  it("posts a comment with an id, and sends the same id again after a failure", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const url = `${TASKS}/${task.id}/comments`;
    let posts = 0;
    const { calls } = openTask(task, {
      boards: [personal],
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== url) return undefined;
        posts += 1;
        return posts === 1
          ? apiError(500, "internal", "Комментарий не отправлен")
          : json(201, commentOf(USER_SUMMARY, "Купить яйца"));
      },
    });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await user.type(
      await within(dialog).findByRole("textbox", { name: "Новый комментарий" }),
      "Купить яйца",
    );
    await user.click(within(dialog).getByRole("button", { name: "Отправить" }));
    expect(await within(dialog).findByText("Комментарий не отправлен")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Отправить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(2));
    const [first, second] = await Promise.all(
      requestsTo(calls, "POST", url).map((request) => bodyOf(request)),
    );
    expect(first).toEqual({ id: expect.stringMatching(/^[0-9a-f-]{36}$/), body: "Купить яйца" });
    expect(second!.id).toBe(first!.id);
  });

  it("gives a viewer no comment form, and no edit or delete on the comments", async () => {
    const shared = makeBoard({ is_shared: true, my_role: "viewer", name: "Общая" });
    const task = makeTask({ board_id: shared.id, title: "Купить хлеб" });
    openTask(task, { boards: [shared], comments: [commentOf(USER_SUMMARY, "Мой комментарий")] });

    const dialog = await formDialog("Задача");
    expect(await within(dialog).findByText("Мой комментарий")).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("textbox", { name: "Новый комментарий" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Изменить" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Удалить" })).not.toBeInTheDocument();
  });

  it("gives an editor edit and delete on an own comment, and nothing on someone else's", async () => {
    const family = makeBoard({
      is_shared: true,
      my_role: "editor",
      name: "Семья",
      members: [USER_SUMMARY, ZHENYA],
    });
    const task = makeTask({ board_id: family.id, title: "Купить хлеб" });
    openTask(task, {
      boards: [family],
      comments: [commentOf(USER_SUMMARY, "Мой"), commentOf(ZHENYA, "Чужой")],
    });

    const dialog = await formDialog("Задача");
    const own = (await within(dialog).findByText("Мой")).closest("li")!;
    const other = within(dialog).getByText("Чужой").closest("li")!;
    expect(within(own).getByRole("button", { name: "Изменить" })).toBeInTheDocument();
    expect(within(own).getByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(within(other).queryByRole("button", { name: "Изменить" })).not.toBeInTheDocument();
    expect(within(other).queryByRole("button", { name: "Удалить" })).not.toBeInTheDocument();
  });

  it("lets an owner delete someone else's comment, but not edit it", async () => {
    const family = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const task = makeTask({ board_id: family.id, title: "Купить хлеб" });
    openTask(task, { boards: [family], comments: [commentOf(ZHENYA, "Чужой")] });

    const dialog = await formDialog("Задача");
    const other = (await within(dialog).findByText("Чужой")).closest("li")!;
    expect(within(other).getByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(within(other).queryByRole("button", { name: "Изменить" })).not.toBeInTheDocument();
  });

  it("shows the history with the text of each record and the name of who did it", async () => {
    const personal = makeBoard({ is_default: true });
    const task = makeTask({ board_id: personal.id, title: "Купить хлеб" });
    const now = new Date().toISOString();
    const activity: TaskActivity[] = [
      { id: 1, kind: "created", actor: ZHENYA, data: {}, created_at: now },
      {
        id: 2,
        kind: "moved",
        actor: USER_SUMMARY,
        data: { from_column: "К выполнению", to_column: "Готово" },
        created_at: now,
      },
    ];
    openTask(task, { boards: [personal], activity });

    const user = userEvent.setup();
    const dialog = await formDialog("Задача");
    await user.click(await within(dialog).findByRole("radio", { name: "История" }));

    const created = (await within(dialog).findByText("Карточка создана")).closest("li")!;
    expect(within(created).getByText(ZHENYA.display_name)).toBeInTheDocument();
    const moved = within(dialog).getByText("Перенос: К выполнению → Готово").closest("li")!;
    expect(within(moved).getByText(USER_SUMMARY.display_name)).toBeInTheDocument();
  });
});
