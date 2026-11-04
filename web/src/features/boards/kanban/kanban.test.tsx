import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Board, BoardColumn, BoardRole, Label, Task } from "../../../api/client";
import {
  API,
  apiError,
  bodyOf,
  json,
  makeBoard,
  makeColumn,
  makeLabel,
  makeTask,
  path,
  renderApp,
  requestsTo,
  searchOf,
  stubApp,
  type Stub,
} from "../../tasks/testing";

const BOARDS = `${API}/boards`;
const TASKS = `${API}/tasks`;
/** Fixed, so tasks can name their board before the test renders it. */
const BOARD_ID = "5f0c2d7e-3b1a-4c8e-9d2f-6a7b8c9d0e1f";

beforeEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.cookie = "planny_csrf=; max-age=0";
});

/** Renders the board of the test, which opens in the Kanban view. */
function renderBoard({
  role = "owner",
  columns,
  tasks = [],
  labels = [],
  boards = [],
  onRequest,
}: {
  role?: BoardRole;
  columns: BoardColumn[];
  tasks?: Task[];
  labels?: Label[];
  boards?: Board[];
  onRequest?: Stub;
}) {
  const board = makeBoard({ id: BOARD_ID, name: "Семья", default_view: "kanban", my_role: role });
  const calls = stubApp({ boards: [board, ...boards], columns, tasks, labels, onRequest });
  return { board, calls, ...renderApp(`/boards/${BOARD_ID}`) };
}

/** Two open columns with cards, and one done column without any. */
function standard() {
  const todo = makeColumn({ name: "К выполнению", position: "a", task_count: 2 });
  const doing = makeColumn({ name: "В работе", position: "b", task_count: 1 });
  const done = makeColumn({ name: "Готово", position: "c", is_done: true });
  const urgent = makeLabel({ name: "Срочно", color: "red" });
  const bread = makeTask({
    board_id: BOARD_ID,
    column_id: todo.id,
    title: "Купить хлеб",
    position: "a",
    labels: [urgent],
    checklist: [
      { id: "c1", text: "Батон", is_done: true, position: "a" },
      { id: "c2", text: "Молоко", is_done: false, position: "b" },
    ],
    comments_count: 2,
  });
  const call = makeTask({
    board_id: BOARD_ID,
    column_id: todo.id,
    title: "Позвонить маме",
    position: "b",
  });
  const letter = makeTask({
    board_id: BOARD_ID,
    column_id: doing.id,
    title: "Написать письмо",
    position: "a",
  });
  return {
    todo,
    doing,
    done,
    urgent,
    bread,
    call,
    letter,
    columns: [todo, doing, done],
    tasks: [bread, call, letter],
  };
}

const column = (name: string) => screen.getByRole("region", { name });

/** The header of a column, which holds its name and its count. */
function headerOf(name: string): HTMLElement {
  return within(column(name)).getByRole("heading", { name }).parentElement!;
}

/** The `li` of a card, found from its title. */
function cardOf(title: string): HTMLElement {
  return screen.getByText(title).closest<HTMLElement>("[data-card-id]")!;
}

/** The button of a card that opens it and lifts it with Space. */
function cardButton(title: string): HTMLElement {
  return screen.getByText(title).closest("button")!;
}

/** What the page announces, from every status region on it. */
function announced(): string {
  return screen
    .getAllByRole("status")
    .map((element) => element.textContent)
    .join(" ");
}

function moveRequests(calls: Request[], taskId: string): Request[] {
  return requestsTo(calls, "POST", `${TASKS}/${taskId}/move`);
}

describe("columns and cards", () => {
  it("shows the columns with their names, counts and cards, and the card details", async () => {
    const { columns, tasks, urgent } = standard();
    renderBoard({ columns, tasks, labels: [urgent] });

    const todo = await screen.findByRole("region", { name: "К выполнению" });
    expect(await within(todo).findByText("Купить хлеб")).toBeInTheDocument();
    expect(within(todo).getByText("Позвонить маме")).toBeInTheDocument();
    expect(within(headerOf("К выполнению")).getByText("2")).toBeInTheDocument();

    const doing = column("В работе");
    expect(within(doing).getByText("Написать письмо")).toBeInTheDocument();
    expect(within(headerOf("В работе")).getByText("1")).toBeInTheDocument();

    const card = cardOf("Купить хлеб");
    expect(within(card).getByText("Срочно")).toBeInTheDocument();
    expect(within(card).getByLabelText("Комментариев: 2")).toBeInTheDocument();
    expect(within(card).getByText("1/2")).toBeInTheDocument();
  });

  it("says an empty column is ready for a card to be dropped on it", async () => {
    const { columns, tasks } = standard();
    renderBoard({ columns, tasks });

    expect(
      await within(await screen.findByRole("region", { name: "Готово" })).findByText(
        "Перетащите карточку сюда",
      ),
    ).toBeInTheDocument();
  });

  it("says an empty column has no cards to a viewer", async () => {
    const { columns, tasks } = standard();
    renderBoard({ role: "viewer", columns, tasks });

    expect(
      await within(await screen.findByRole("region", { name: "Готово" })).findByText(
        "Карточек нет",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Перетащите карточку сюда")).not.toBeInTheDocument();
  });

  it("gives a viewer no menus, no quick add and no new column, and Space on a card does nothing", async () => {
    const { columns, tasks, urgent } = standard();
    const { calls } = renderBoard({ role: "viewer", columns, tasks, labels: [urgent] });

    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(screen.getByText("Только чтение")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Меню колонки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Меню карточки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Добавить задачу" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Колонка" })).not.toBeInTheDocument();

    // A key press that reaches a viewer's card must not lift it.
    fireEvent.keyDown(cardButton("Купить хлеб"), { key: " " });

    expect(announced()).not.toContain("взята");
    expect(within(column("К выполнению")).getByText("Купить хлеб")).toBeInTheDocument();
    expect(calls.filter((request) => request.method !== "GET")).toHaveLength(0);
  });
});

describe("keyboard moves", () => {
  it("moves a card to the same place in the next column with Space, ArrowRight and Space", async () => {
    const { doing, columns, tasks, urgent, bread } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      labels: [urgent],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${bread.id}/move`
          ? json(200, bread)
          : undefined,
    });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");
    await user.keyboard("{ArrowRight}");
    await user.keyboard(" ");

    await waitFor(() => expect(moveRequests(calls, bread.id)).toHaveLength(1));
    expect(await bodyOf(moveRequests(calls, bread.id)[0]!)).toEqual({
      column_id: doing.id,
      after_id: null,
    });
  });

  it("moves a card down its column to after the next card", async () => {
    const { todo, columns, tasks, urgent, bread, call } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      labels: [urgent],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${bread.id}/move`
          ? json(200, bread)
          : undefined,
    });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");
    await user.keyboard("{ArrowDown}");
    await user.keyboard(" ");

    await waitFor(() => expect(moveRequests(calls, bread.id)).toHaveLength(1));
    expect(await bodyOf(moveRequests(calls, bread.id)[0]!)).toEqual({
      column_id: todo.id,
      after_id: call.id,
    });
  });

  it("announces the lifted card by its title", async () => {
    const { columns, tasks, urgent } = standard();
    renderBoard({ columns, tasks, labels: [urgent] });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");

    await waitFor(() => expect(announced()).toContain("Карточка «Купить хлеб» взята"));
  });

  it("sends nothing when the lifted card is cancelled with Escape", async () => {
    const { columns, tasks, urgent, bread } = standard();
    const { calls } = renderBoard({ columns, tasks, labels: [urgent] });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");
    await user.keyboard("{ArrowRight}");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(announced()).toContain("Перенос отменён"));
    expect(moveRequests(calls, bread.id)).toHaveLength(0);
  });

  it("sends nothing when the lifted card is dropped where it already is", async () => {
    const { columns, tasks, urgent, bread } = standard();
    const { calls } = renderBoard({ columns, tasks, labels: [urgent] });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");
    await user.keyboard(" ");

    await waitFor(() => expect(announced()).toContain("Карточка отпущена"));
    expect(moveRequests(calls, bread.id)).toHaveLength(0);
  });

  it("shows a toast and puts the card back in its column when the move fails", async () => {
    const { columns, tasks, urgent, bread } = standard();
    renderBoard({
      columns,
      tasks,
      labels: [urgent],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${bread.id}/move`
          ? apiError(500, "internal", "Сбой на сервере")
          : undefined,
    });
    await screen.findByText("Купить хлеб");

    const user = userEvent.setup();
    cardButton("Купить хлеб").focus();
    await user.keyboard(" ");
    await user.keyboard("{ArrowRight}");
    await user.keyboard(" ");

    expect(await screen.findByText("Не удалось перенести карточку")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(column("В работе")).queryByText("Купить хлеб")).not.toBeInTheDocument(),
    );
    expect(within(column("К выполнению")).getByText("Купить хлеб")).toBeInTheDocument();
  });
});

describe("column menu", () => {
  it("disables Delete on the last done column and says why", async () => {
    const { columns, tasks } = standard();
    renderBoard({ columns, tasks });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: Готово" }));
    const remove = screen.getByRole("menuitem", { name: "Удалить" });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAccessibleDescription("Это последняя завершающая колонка");

    await user.click(remove);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers the other columns when a column with cards is deleted, and moves the cards there", async () => {
    const { todo, doing, done, columns, tasks } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "DELETE" ? new Response(null, { status: 204 }) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: К выполнению" }));
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Удалить колонку «К выполнению»?",
    });

    const target = within(dialog).getByRole("combobox", { name: "Куда перенести 2 карточки" });
    expect(
      within(target)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([doing.name, done.name]);
    await user.selectOptions(target, done.id);
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${todo.id}`;
    await waitFor(() => expect(requestsTo(calls, "DELETE", url)).toHaveLength(1));
    const [request] = requestsTo(calls, "DELETE", url);
    expect(searchOf(request!).get("move_to")).toBe(done.id);
  });

  it("asks for confirmation before a column with cards is marked done", async () => {
    const todo = makeColumn({ name: "К выполнению", position: "a" });
    const doing = makeColumn({ name: "В работе", position: "b", task_count: 3 });
    const done = makeColumn({ name: "Готово", position: "c", is_done: true });
    const tasks = ["Один", "Два", "Три"].map((title) =>
      makeTask({ board_id: BOARD_ID, column_id: doing.id, title }),
    );
    const { calls } = renderBoard({
      columns: [todo, doing, done],
      tasks,
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { ...doing, is_done: true }) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: В работе" }));
    await user.click(screen.getByRole("menuitem", { name: "Отметить как завершающую" }));
    const dialog = await screen.findByRole("dialog", { name: "Сделать колонку завершающей?" });
    expect(within(dialog).getByText("Будут отмечены выполненными 3 карточки")).toBeInTheDocument();
    expect(requestsTo(calls, "PATCH", `${BOARDS}/${BOARD_ID}/columns/${doing.id}`)).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Подтвердить" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${doing.id}`;
    await waitFor(() => expect(requestsTo(calls, "PATCH", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", url)[0]!)).toEqual({ is_done: true });
  });

  it("marks an empty column done at once, without a dialog", async () => {
    const todo = makeColumn({ name: "К выполнению", position: "a" });
    const doing = makeColumn({ name: "В работе", position: "b", task_count: 1 });
    const done = makeColumn({ name: "Готово", position: "c", is_done: true });
    const { calls } = renderBoard({
      columns: [todo, doing, done],
      tasks: [makeTask({ board_id: BOARD_ID, column_id: doing.id, title: "Написать письмо" })],
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { ...todo, is_done: true }) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: К выполнению" }));
    await user.click(screen.getByRole("menuitem", { name: "Отметить как завершающую" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${todo.id}`;
    await waitFor(() => expect(requestsTo(calls, "PATCH", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", url)[0]!)).toEqual({ is_done: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("warns how many cards lose the done mark, and removes it after confirming", async () => {
    const todo = makeColumn({ name: "К выполнению", position: "a" });
    const finished = makeColumn({ name: "Готово", position: "b", is_done: true, task_count: 2 });
    const archive = makeColumn({ name: "Архив", position: "c", is_done: true });
    const tasks = ["Отчёт", "Счёт"].map((title) =>
      makeTask({
        board_id: BOARD_ID,
        column_id: finished.id,
        title,
        completed_at: "2026-01-01T00:00:00Z",
      }),
    );
    const { calls } = renderBoard({
      columns: [todo, finished, archive],
      tasks,
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { ...finished, is_done: false }) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: Готово" }));
    await user.click(screen.getByRole("menuitem", { name: "Снять отметку завершающей" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Снять отметку завершающей?",
    });
    expect(
      within(dialog).getByText("Отметка о выполнении будет снята у 2 карточек"),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Подтвердить" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${finished.id}`;
    await waitFor(() => expect(requestsTo(calls, "PATCH", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", url)[0]!)).toEqual({ is_done: false });
  });

  it("renames a column", async () => {
    const { todo, columns, tasks } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { ...todo, name: "Сделать" }) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: К выполнению" }));
    await user.click(screen.getByRole("menuitem", { name: "Переименовать" }));
    const dialog = await screen.findByRole("dialog", { name: "Переименовать колонку" });
    const name = within(dialog).getByRole("textbox", { name: "Название" });
    await user.clear(name);
    await user.type(name, "Сделать");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${todo.id}`;
    await waitFor(() => expect(requestsTo(calls, "PATCH", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "PATCH", url)[0]!)).toEqual({ name: "Сделать" });
  });

  it("moves a column one place to the right, after the column that is next to it", async () => {
    const { todo, doing, columns, tasks } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request).endsWith("/move") ? json(200, todo) : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню колонки: К выполнению" }));
    await user.click(screen.getByRole("menuitem", { name: "Переместить вправо" }));

    const url = `${BOARDS}/${BOARD_ID}/columns/${todo.id}/move`;
    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", url)[0]!)).toEqual({ after_id: doing.id });
  });
});

describe("adding", () => {
  it("adds a column with a name, an id and no done mark", async () => {
    const { columns, tasks } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${BOARDS}/${BOARD_ID}/columns`
          ? json(201, makeColumn({ name: "Ожидание" }))
          : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Колонка" }));
    const dialog = await screen.findByRole("dialog", { name: "Новая колонка" });
    await user.type(within(dialog).getByRole("textbox", { name: "Название" }), "Ожидание");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const url = `${BOARDS}/${BOARD_ID}/columns`;
    await waitFor(() => expect(requestsTo(calls, "POST", url)).toHaveLength(1));
    const body = await bodyOf(requestsTo(calls, "POST", url)[0]!);
    expect(body).toMatchObject({ name: "Ожидание", is_done: false });
    expect(body.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("adds a card to its column with the column's id", async () => {
    const { todo, columns, tasks } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request) === TASKS ? json(201, {}) : undefined,
    });

    const user = userEvent.setup();
    const todoColumn = await screen.findByRole("region", { name: "К выполнению" });
    await user.click(within(todoColumn).getByRole("button", { name: "Добавить задачу" }));
    await user.type(
      within(todoColumn).getByRole("textbox", { name: "Название задачи" }),
      "Полить цветы",
    );
    await user.click(within(todoColumn).getByRole("button", { name: "Добавить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", TASKS)[0]!)).toMatchObject({
      title: "Полить цветы",
      board_id: BOARD_ID,
      column_id: todo.id,
      priority: 3,
    });
  });
});

describe("card menu", () => {
  it("moves a card to the top of another column", async () => {
    const { doing, columns, tasks, call } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${call.id}/move`
          ? json(200, call)
          : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню карточки: Позвонить маме" }));
    await user.click(screen.getByRole("menuitem", { name: "Переместить в…" }));
    const dialog = await screen.findByRole("dialog", { name: "Переместить в…" });
    await within(dialog).findByRole("option", { name: "В работе" });

    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Колонка" }), doing.id);
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Место" }), "В начало");
    await user.click(within(dialog).getByRole("button", { name: "Переместить" }));

    await waitFor(() => expect(moveRequests(calls, call.id)).toHaveLength(1));
    expect(await bodyOf(moveRequests(calls, call.id)[0]!)).toEqual({
      column_id: doing.id,
      after_id: null,
    });
  });

  it("moves a card to the end of a column with cards without naming a card after it", async () => {
    const { doing, columns, tasks, call } = standard();
    const { calls } = renderBoard({
      columns,
      tasks,
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${TASKS}/${call.id}/move`
          ? json(200, call)
          : undefined,
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню карточки: Позвонить маме" }));
    await user.click(screen.getByRole("menuitem", { name: "Переместить в…" }));
    const dialog = await screen.findByRole("dialog", { name: "Переместить в…" });
    await within(dialog).findByRole("option", { name: "В работе" });

    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Колонка" }), doing.id);
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Место" }), "В конец");
    await user.click(within(dialog).getByRole("button", { name: "Переместить" }));

    await waitFor(() => expect(moveRequests(calls, call.id)).toHaveLength(1));
    const body = await bodyOf(moveRequests(calls, call.id)[0]!);
    expect(body).toMatchObject({ column_id: doing.id });
    expect(body).not.toHaveProperty("after_id");
  });

  it("warns about labels only once another board is chosen", async () => {
    const { columns, tasks } = standard();
    const other = makeBoard({ name: "Дача" });
    renderBoard({ columns, tasks, boards: [other] });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Меню карточки: Позвонить маме" }));
    await user.click(screen.getByRole("menuitem", { name: "Переместить в…" }));
    const dialog = await screen.findByRole("dialog", { name: "Переместить в…" });
    await within(dialog).findByRole("option", { name: "Дача" });

    expect(screen.queryByText(/Метки сбросятся/)).not.toBeInTheDocument();

    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Доска" }), other.id);

    expect(
      within(dialog).getByText(
        "Метки сбросятся, а исполнители, которых нет на новой доске, будут сняты.",
      ),
    ).toBeInTheDocument();
  });
});
