import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Label, UserSummary } from "../../api/client";
import { BOARDS_KEY } from "../../api/queryClient";
import { holdUpdates, releaseUpdates, whenReleased } from "../sync/hold";
import {
  API,
  bodyOf,
  json,
  makeBoard,
  makeColumn,
  makeDeadline,
  makeLabel,
  makeTask,
  path,
  renderApp,
  requestsTo,
  searchOf,
  stubApp,
  USER_SUMMARY,
} from "../tasks/testing";

const TASKS = `${API}/tasks`;

beforeEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.cookie = "planny_csrf=; max-age=0";
});

afterEach(() => {
  vi.restoreAllMocks();
  releaseUpdates();
});

/** A board with one open column and one card, in the given default view. */
function setup(defaultView: "list" | "kanban", labels: Label[] = []) {
  const board = makeBoard({ name: "Семья", default_view: defaultView });
  const todo = makeColumn({ name: "К выполнению", task_count: 1 });
  const task = makeTask({ board_id: board.id, column_id: todo.id, title: "Купить хлеб" });
  const calls = stubApp({ boards: [board], columns: [todo], tasks: [task], labels });
  return { board, calls };
}

describe("board view", () => {
  it("opens the default view of the board when no view was chosen", async () => {
    const { board } = setup("kanban");
    renderApp(`/boards/${board.id}`);

    expect(await screen.findByRole("region", { name: "К выполнению" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kanban" })).toHaveAttribute("aria-checked", "true");
  });

  it("opens the list when the board defaults to it", async () => {
    const { board } = setup("list");
    renderApp(`/boards/${board.id}`);

    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Список" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("region", { name: "К выполнению" })).not.toBeInTheDocument();
  });

  it("remembers a chosen view for the board, so it opens that way again", async () => {
    const user = userEvent.setup();
    const { board } = setup("list");
    const first = renderApp(`/boards/${board.id}`);

    await user.click(await screen.findByRole("radio", { name: "Kanban" }));
    expect(localStorage.getItem(`planny.board-view.${board.id}`)).toBe("kanban");
    first.unmount();

    // Same board, default still the list: the saved choice wins.
    renderApp(`/boards/${board.id}`);
    expect(await screen.findByRole("region", { name: "К выполнению" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kanban" })).toHaveAttribute("aria-checked", "true");
  });

  it("still renders the page and switches the view when local storage fails", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Storage is disabled");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage is disabled");
    });
    const user = userEvent.setup();
    const { board } = setup("list");
    renderApp(`/boards/${board.id}`);

    expect(await screen.findByRole("heading", { name: "Семья" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Список" })).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("radio", { name: "Kanban" }));

    expect(await screen.findByRole("region", { name: "К выполнению" })).toBeInTheDocument();
  });

  it("shows the calendar of the board, all of it until the filters narrow it", async () => {
    const urgent = makeLabel({ name: "Срочно" });
    const { board } = setup("list", [urgent]);
    const calls = stubApp({
      boards: [board],
      labels: [urgent],
      calendarItems: [makeDeadline({ title: "Купить хлеб", board_id: board.id })],
    });
    const lastRequest = () => {
      const request = requestsTo(calls, "GET", `${API}/calendar/items`).at(-1);
      return request && searchOf(request);
    };
    const user = userEvent.setup();
    renderApp(`/boards/${board.id}`);

    await user.click(await screen.findByRole("radio", { name: "Календарь" }));

    await waitFor(() => expect(lastRequest()?.get("board_id")).toBe(board.id));
    expect(lastRequest()?.has("assignee")).toBe(false);
    expect(lastRequest()?.has("label_id")).toBe(false);

    await user.click(screen.getByRole("switch", { name: "Только мои" }));
    await user.selectOptions(await screen.findByRole("combobox", { name: "Метка" }), urgent.id);

    await waitFor(() => expect(lastRequest()?.get("label_id")).toBe(urgent.id));
    expect(lastRequest()?.get("assignee")).toBe("me");
    expect(lastRequest()?.get("board_id")).toBe(board.id);
  });

  it("remembers the calendar as the chosen view", async () => {
    const { board } = setup("list");
    const user = userEvent.setup();
    const first = renderApp(`/boards/${board.id}`);
    await user.click(await screen.findByRole("radio", { name: "Календарь" }));
    first.unmount();

    renderApp(`/boards/${board.id}`);

    expect(await screen.findByRole("radio", { name: "Календарь" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});

/** The panel of one column in the list, found from its heading. */
function panelOf(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("button")!.parentElement!;
}

describe("new task from a column of the list", () => {
  it("creates the task in the empty column whose button was pressed", async () => {
    const board = makeBoard({ name: "Семья", default_view: "list" });
    const todo = makeColumn({ name: "К выполнению", task_count: 1 });
    const doing = makeColumn({ name: "В работе" });
    const task = makeTask({ board_id: board.id, column_id: todo.id, title: "Купить хлеб" });
    const calls = stubApp({
      boards: [board],
      columns: [todo, doing],
      tasks: [task],
      onRequest: (request) =>
        request.method === "POST" && path(request) === TASKS ? json(201, makeTask()) : undefined,
    });
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "В работе" });
    await user.click(
      await within(panelOf("В работе")).findByRole("button", { name: "Новая задача" }),
    );

    await screen.findByRole("textbox", { name: "Название" });
    const dialog = screen.getByRole("dialog", { name: "Новая задача" });
    await user.type(within(dialog).getByRole("textbox", { name: "Название" }), "Полить цветы");
    expect(within(dialog).getByLabelText("Колонка")).toHaveValue(doing.id);
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", TASKS)).toHaveLength(1));
    expect(await bodyOf(requestsTo(calls, "POST", TASKS)[0]!)).toMatchObject({
      board_id: board.id,
      column_id: doing.id,
      title: "Полить цветы",
    });
  });
});

describe("label filter", () => {
  it("is not shown on a board without labels", async () => {
    const { board } = setup("list");
    const { client } = renderApp(`/boards/${board.id}`);

    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    // The labels have answered by now, and there are none.
    await waitFor(() =>
      expect(client.getQueryState([...BOARDS_KEY, "labels", board.id])?.status).toBe("success"),
    );
    expect(screen.queryByRole("combobox", { name: "Метка" })).not.toBeInTheDocument();
  });

  it("sends the chosen label with the task requests", async () => {
    const urgent = makeLabel({ name: "Срочно" });
    const { board, calls } = setup("list", [urgent]);
    renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Метка" }), urgent.id);

    await waitFor(() =>
      expect(
        requestsTo(calls, "GET", TASKS).some(
          (request) => searchOf(request).get("label_id") === urgent.id,
        ),
      ).toBe(true),
    );
  });

  it("stops filtering by a label that the board no longer has", async () => {
    const urgent = makeLabel({ name: "Срочно" });
    const board = makeBoard({ name: "Семья" });
    const todo = makeColumn({ name: "К выполнению", task_count: 2 });
    const tagged = makeTask({
      board_id: board.id,
      column_id: todo.id,
      title: "Купить хлеб",
      labels: [urgent],
    });
    const plain = makeTask({ board_id: board.id, column_id: todo.id, title: "Позвонить маме" });
    const labels = [urgent];
    const calls = stubApp({ boards: [board], columns: [todo], tasks: [tagged, plain], labels });
    const { client } = renderApp(`/boards/${board.id}`);

    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Метка" }), urgent.id);
    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(screen.queryByText("Позвонить маме")).not.toBeInTheDocument();

    // The label is taken off the board, and the board's labels are loaded again.
    labels.splice(0);
    const before = calls.length;
    await act(async () => {
      await client.invalidateQueries({ queryKey: BOARDS_KEY });
    });

    expect(await screen.findByText("Позвонить маме")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Метка" })).not.toBeInTheDocument();
    const sent = requestsTo(calls.slice(before), "GET", TASKS);
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.filter((request) => searchOf(request).has("label_id"))).toHaveLength(0);
  });
});

describe("switching boards", () => {
  it("opens another board with no label chosen and in its own default view", async () => {
    const urgent = makeLabel({ name: "Срочно" });
    const family = makeBoard({ name: "Семья", default_view: "list" });
    const cottage = makeBoard({ name: "Дача", default_view: "list" });
    const todo = makeColumn({ name: "К выполнению", task_count: 2 });
    const tagged = makeTask({
      board_id: family.id,
      column_id: todo.id,
      title: "Купить хлеб",
      labels: [urgent],
    });
    const plain = makeTask({ board_id: cottage.id, column_id: todo.id, title: "Полить грядки" });
    const calls = stubApp({
      boards: [family, cottage],
      columns: [todo],
      tasks: [tagged, plain],
      labels: [urgent],
    });
    renderApp(`/boards/${family.id}`);

    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Метка" }), urgent.id);
    await user.click(screen.getByRole("radio", { name: "Kanban" }));
    expect(await screen.findByRole("region", { name: "К выполнению" })).toBeInTheDocument();

    const before = calls.length;
    await user.click(screen.getByRole("link", { name: "Дача" }));

    expect(await screen.findByText("Полить грядки")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Дача" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Список" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("region", { name: "К выполнению" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Метка" })).toHaveValue("");
    const sent = requestsTo(calls.slice(before), "GET", TASKS);
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.filter((request) => searchOf(request).has("label_id"))).toHaveLength(0);
  });
});

describe("assignee filter", () => {
  it("stops filtering by an assignee who is no longer a member of the shared board", async () => {
    const zhenya: UserSummary = { id: "u2", display_name: "Женя", color: "pink" };
    const family = makeBoard({ name: "Семья", is_shared: true, members: [USER_SUMMARY, zhenya] });
    const todo = makeColumn({ name: "К выполнению", task_count: 2 });
    const mine = makeTask({
      board_id: family.id,
      column_id: todo.id,
      title: "Купить хлеб",
      assignees: [zhenya],
    });
    const other = makeTask({ board_id: family.id, column_id: todo.id, title: "Позвонить маме" });
    const calls = stubApp({ boards: [family], columns: [todo], tasks: [mine, other] });
    const { client } = renderApp(`/boards/${family.id}`);

    const user = userEvent.setup();
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Исполнитель" }),
      zhenya.id,
    );
    expect(await screen.findByText("Купить хлеб")).toBeInTheDocument();
    expect(screen.queryByText("Позвонить маме")).not.toBeInTheDocument();

    // Женя leaves the board, and the board is loaded again.
    family.members = [USER_SUMMARY];
    const before = calls.length;
    await act(async () => {
      await client.invalidateQueries({ queryKey: BOARDS_KEY });
    });

    expect(await screen.findByText("Позвонить маме")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Женя" })).not.toBeInTheDocument();
    const sent = requestsTo(calls.slice(before), "GET", TASKS);
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.filter((request) => searchOf(request).has("assignee"))).toHaveLength(0);
  });
});

describe("sync hold", () => {
  it("runs an update at once when nothing is held", () => {
    const update = vi.fn();

    whenReleased(update);

    expect(update).toHaveBeenCalledTimes(1);
  });

  it("waits during a hold and runs each update once on release", () => {
    const first = vi.fn();
    const second = vi.fn();
    holdUpdates();

    whenReleased(first);
    whenReleased(second);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();

    releaseUpdates();
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    // A second release has nothing left to run.
    releaseUpdates();
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });
});
