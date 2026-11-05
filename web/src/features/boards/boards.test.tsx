import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UserSummary } from "../../api/client";
import { BOARDS_KEY } from "../../api/queryClient";
import {
  API,
  apiError,
  bodyOf,
  json,
  makeBoard,
  makeColumn,
  makeTask,
  path,
  renderApp,
  requestsTo,
  searchOf,
  stubApp,
  USER_SUMMARY,
} from "../tasks/testing";

const TASKS = `${API}/tasks`;
const BOARDS = `${API}/boards`;
const ZHENYA: UserSummary = { id: "u2", display_name: "Женя", color: "pink" };

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

/** The panel of one column or section, found from its heading. */
function panelOf(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("button")!.parentElement!;
}

describe("boards list", () => {
  it("shows the personal and shared sections with open task counts", async () => {
    const personal = makeBoard({ is_default: true, name: "Личные", open_tasks_count: 2 });
    const shared = makeBoard({
      is_shared: true,
      name: "Семья",
      open_tasks_count: 5,
      members: [USER_SUMMARY, ZHENYA],
    });
    stubApp({ boards: [personal, shared] });
    renderApp("/boards");

    expect(await screen.findByRole("heading", { name: "Личные" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Общие" })).toBeInTheDocument();
    expect(screen.getByText("2 задачи")).toBeInTheDocument();
    expect(screen.getByText("5 задач")).toBeInTheDocument();
  });

  it("offers a new board from the empty list, which opens the board dialog", async () => {
    stubApp({ boards: [] });
    renderApp("/boards");

    const user = userEvent.setup();
    // The header has a button of the same name, so look for the one in the empty state.
    const empty = (await screen.findByText("Досок нет")).parentElement!;
    await user.click(within(empty).getByRole("button", { name: "Новая доска" }));

    expect(await screen.findByRole("dialog", { name: "Новая доска" })).toBeInTheDocument();
  });

  it("creates a board with POST /boards", async () => {
    const personal = makeBoard({ is_default: true, name: "Личные" });
    const boards = [personal];
    const created = makeBoard({ name: "Семья" });
    const calls = stubApp({
      boards,
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== BOARDS) return undefined;
        boards.push(created);
        return json(201, created);
      },
    });
    renderApp("/boards");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая доска" }));
    const dialog = await screen.findByRole("dialog", { name: "Новая доска" });
    await user.type(within(dialog).getByRole("textbox", { name: "Название" }), "Семья");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", BOARDS)).toHaveLength(1));
    const [post] = requestsTo(calls, "POST", BOARDS);
    const body = await bodyOf(post!);
    expect(body).toMatchObject({ name: "Семья", icon: "list-checks", default_view: "list" });
    expect(body.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("sends the same id again when a failed create is repeated", async () => {
    const personal = makeBoard({ is_default: true, name: "Личные" });
    const created = makeBoard({ name: "Семья" });
    const boards = [personal];
    let posts = 0;
    const calls = stubApp({
      boards,
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== BOARDS) return undefined;
        posts += 1;
        if (posts === 1) return apiError(500, "internal", "Не удалось создать доску");
        boards.push(created);
        return json(201, created);
      },
    });
    renderApp("/boards");

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Новая доска" }));
    const dialog = await screen.findByRole("dialog", { name: "Новая доска" });
    await user.type(within(dialog).getByRole("textbox", { name: "Название" }), "Семья");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await within(dialog).findByText("Не удалось создать доску")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", BOARDS)).toHaveLength(2));
    const [first, second] = await Promise.all(
      requestsTo(calls, "POST", BOARDS).map((request) => bodyOf(request)),
    );
    expect(first!.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(second!.id).toBe(first!.id);
  });
});

describe("board screen", () => {
  it("shows the columns with their tasks, and loads a done column only when it is opened", async () => {
    const board = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const todo = makeColumn({ name: "К выполнению", task_count: 1 });
    const done = makeColumn({ name: "Готово", is_done: true, task_count: 1 });
    const open = makeTask({ board_id: board.id, column_id: todo.id, title: "Купить хлеб" });
    const finished = makeTask({
      board_id: board.id,
      column_id: done.id,
      title: "Вынести мусор",
      completed_at: new Date().toISOString(),
    });
    const calls = stubApp({ boards: [board], columns: [todo, done], tasks: [open, finished] });
    renderApp(`/boards/${board.id}`);

    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(within(panelOf("К выполнению")).getByText("Купить хлеб")).toBeInTheDocument();

    const doneRequests = () =>
      requestsTo(calls, "GET", TASKS).filter(
        (request) => searchOf(request).get("column_id") === done.id,
      );
    const doneHeader = screen.getByRole("heading", { name: "Готово" }).closest("button")!;
    expect(doneHeader).toHaveAttribute("aria-expanded", "false");
    expect(doneRequests()).toHaveLength(0);
    expect(screen.queryByText("Вынести мусор")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(doneHeader);

    expect(await screen.findByText("Вынести мусор")).toBeInTheDocument();
    expect(doneRequests()).toHaveLength(1);
  });

  it("marks a viewer's board read-only and offers no quick add", async () => {
    const board = makeBoard({ is_shared: true, my_role: "viewer", name: "Общая" });
    const column = makeColumn({ name: "К выполнению" });
    const task = makeTask({ board_id: board.id, column_id: column.id, title: "Купить хлеб" });
    stubApp({ boards: [board], columns: [column], tasks: [task] });
    renderApp(`/boards/${board.id}`);

    // The columns come in after the board, so wait for a card before checking the quick add.
    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(screen.getByText("Только чтение")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Быстро добавить" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Выполнить: Купить хлеб" })).toBeDisabled();
  });

  it("says the board no longer exists when it is missing", async () => {
    stubApp({ boards: [] });
    renderApp("/boards/missing");

    expect(await screen.findByText("Объект больше не существует")).toBeInTheDocument();
  });

  it("sends PATCH when the owner changes a member's role", async () => {
    const board = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const calls = stubApp({
      boards: [board],
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { user: ZHENYA, role: "viewer" }) : undefined,
    });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    await user.selectOptions(
      await within(dialog).findByRole("combobox", { name: "Роль: Женя" }),
      "viewer",
    );

    await waitFor(() =>
      expect(requestsTo(calls, "PATCH", `${BOARDS}/${board.id}/members/${ZHENYA.id}`)).toHaveLength(
        1,
      ),
    );
    const [patch] = requestsTo(calls, "PATCH", `${BOARDS}/${board.id}/members/${ZHENYA.id}`);
    expect(await bodyOf(patch!)).toEqual({ role: "viewer" });
  });

  it("shows no role selects to a viewer", async () => {
    const board = makeBoard({
      is_shared: true,
      my_role: "viewer",
      name: "Общая",
      members: [USER_SUMMARY, ZHENYA],
    });
    stubApp({ boards: [board] });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });

    // The member list loads on its own, wait until it shows the second member.
    expect(await within(dialog).findByText("Женя")).toBeInTheDocument();
    expect(within(dialog).getByText("Редактор")).toBeInTheDocument();
    expect(within(dialog).queryAllByRole("combobox")).toHaveLength(0);
  });

  it("sends only the changed fields with the version the form started from", async () => {
    const board = makeBoard({
      is_shared: true,
      name: "Семья",
      description: "Старое описание",
      members: [USER_SUMMARY, ZHENYA],
    });
    const boards = [board];
    const calls = stubApp({
      boards,
      onRequest: (request) => (request.method === "PATCH" ? json(200, boards[0]) : undefined),
    });
    const { client } = renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    const name = within(dialog).getByRole("textbox", { name: "Название" });
    await user.clear(name);
    await user.type(name, "Дом");

    // Another owner changes the description and bumps the version while the form is open.
    boards.splice(0, 1, { ...board, description: "Новое описание", version: 2 });
    await act(async () => {
      await client.invalidateQueries({ queryKey: BOARDS_KEY });
    });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(requestsTo(calls, "PATCH", `${BOARDS}/${board.id}`)).toHaveLength(1),
    );
    const [patch] = requestsTo(calls, "PATCH", `${BOARDS}/${board.id}`);
    expect(await bodyOf(patch!)).toEqual({ name: "Дом", version: 1 });
  });

  it("archives over a newer version without asking: the form saves nothing else", async () => {
    const board = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const newer = { ...board, description: "Новое описание", version: board.version + 2 };
    let patches = 0;
    const calls = stubApp({
      boards: [board],
      onRequest: (request) => {
        if (request.method !== "PATCH") return undefined;
        patches += 1;
        return patches === 1
          ? apiError(409, "version_conflict", "Объект изменился", { current: newer })
          : json(200, { ...newer, archived_at: "2026-11-05T10:00:00Z" });
      },
    });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    await user.click(within(dialog).getByRole("button", { name: "Архивировать доску" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const sent = requestsTo(calls, "PATCH", `${API}/boards/${board.id}`);
    expect(sent).toHaveLength(2);
    expect(await bodyOf(sent[1]!)).toEqual({ version: newer.version, archived: true });
  });

  it("repeats a stale save with the newer version and only the changed fields", async () => {
    const board = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const boards = [board];
    const newer = { ...board, description: "Новое описание", version: 3 };
    let patches = 0;
    const calls = stubApp({
      boards,
      onRequest: (request) => {
        if (request.method !== "PATCH") return undefined;
        patches += 1;
        return patches === 1
          ? apiError(409, "version_conflict", "Объект изменился", { current: newer })
          : json(200, newer);
      },
    });
    const { client } = renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    const name = within(dialog).getByRole("textbox", { name: "Название" });
    await user.clear(name);
    await user.type(name, "Дом");

    boards.splice(0, 1, newer);
    await act(async () => {
      await client.invalidateQueries({ queryKey: BOARDS_KEY });
    });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const conflict = await screen.findByRole("dialog", {
      name: "Объект изменился, пока вы его редактировали",
    });
    await user.click(within(conflict).getByRole("button", { name: "Сохранить мои изменения" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const patchesSent = requestsTo(calls, "PATCH", `${BOARDS}/${board.id}`);
    expect(patchesSent).toHaveLength(2);
    expect(await bodyOf(patchesSent[0]!)).toEqual({ name: "Дом", version: 1 });
    expect(await bodyOf(patchesSent[1]!)).toEqual({ name: "Дом", version: 3 });
  });

  it("keeps the settings open and shows the new values when the user asks for the new version", async () => {
    const board = makeBoard({ name: "Семья" });
    const boards = [board];
    const newer = { ...board, name: "Дача", description: "Новое описание", version: 2 };
    stubApp({
      boards,
      onRequest: (request) => {
        if (request.method !== "PATCH") return undefined;
        boards.splice(0, 1, newer);
        return apiError(409, "version_conflict", "Объект изменился", { current: newer });
      },
    });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    const name = within(dialog).getByRole("textbox", { name: "Название" });
    await user.clear(name);
    await user.type(name, "Мой вариант");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const conflict = await screen.findByRole("dialog", {
      name: "Объект изменился, пока вы его редактировали",
    });
    await user.click(within(conflict).getByRole("button", { name: "Показать новую версию" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Объект изменился, пока вы его редактировали" }),
      ).not.toBeInTheDocument(),
    );
    const form = screen.getByRole("dialog", { name: "Настройки доски" });
    expect(within(form).getByRole("textbox", { name: "Название" })).toHaveValue("Дача");
    expect(within(form).getByRole("textbox", { name: "Описание" })).toHaveValue("Новое описание");
  });

  it("sends no PATCH and closes when nothing was changed", async () => {
    const board = makeBoard({ is_shared: true, name: "Семья", members: [USER_SUMMARY, ZHENYA] });
    const calls = stubApp({ boards: [board] });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestsTo(calls, "PATCH", `${BOARDS}/${board.id}`)).toHaveLength(0);
  });
});

describe("show the new version", () => {
  it("uses the newest board even if it changed again after the conflict", async () => {
    const board = makeBoard({ name: "Семья", version: 1 });
    const boards = [board];
    const second = { ...board, name: "Чужое", version: 2 };
    stubApp({
      boards,
      onRequest: (request) => {
        if (request.method !== "PATCH") return undefined;
        boards.splice(0, 1, second);
        return apiError(409, "version_conflict", "Объект изменился", { current: second });
      },
    });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Настройки доски" }));
    const dialog = await screen.findByRole("dialog", { name: "Настройки доски" });
    const name = within(dialog).getByRole("textbox", { name: "Название" });
    await user.clear(name);
    await user.type(name, "Дом");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    const conflict = await screen.findByRole("dialog", {
      name: "Объект изменился, пока вы его редактировали",
    });

    // The server moves on once more, and the cache hears of it only from this button.
    boards.splice(0, 1, { ...board, name: "Третье", version: 3 });
    await user.click(within(conflict).getByRole("button", { name: "Показать новую версию" }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Третье"),
    );
    expect(screen.getByRole("dialog", { name: "Настройки доски" })).toBeInTheDocument();
  });
});
