import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import type {
  Board,
  BoardColumn,
  CurrentUser,
  Notification,
  SyncState,
  Task,
  UserSummary,
} from "../../api/client";
import { App } from "../../App";

export const API = "/bff/api/v1";

export const USER: CurrentUser = {
  id: "u1",
  display_name: "Саша",
  color: "teal",
  login: "sasha",
  timezone: "Europe/Moscow",
  must_change_password: false,
};

export const USER_SUMMARY: UserSummary = {
  id: USER.id,
  display_name: USER.display_name,
  color: USER.color,
};

export type Stub = (request: Request) => Response | Promise<Response> | undefined;

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(
  status: number,
  code: string,
  message: string,
  details: Record<string, unknown> = {},
): Response {
  return json(status, { error: { code, message, details, request_id: "r" } });
}

const UNAUTHORIZED = () => apiError(401, "unauthorized", "Требуется вход");

/** Every fetch goes through `stub`, a request it doesn't answer gets 401. Returns the requests seen. */
export function stubBackend(stub: Stub): Request[] {
  const calls: Request[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo, init?: RequestInit) => {
    const request = new Request(new URL(input as string, "http://localhost"), init);
    const real = input instanceof Request ? input : request;
    calls.push(real);
    return (await stub(real)) ?? UNAUTHORIZED();
  });
  return calls;
}

export function path(request: Request): string {
  return new URL(request.url).pathname;
}

/** The requests with this method and path, in the order they were sent. */
export function requestsTo(calls: Request[], method: string, pathname: string): Request[] {
  return calls.filter((request) => request.method === method && path(request) === pathname);
}

export function searchOf(request: Request): URLSearchParams {
  return new URL(request.url).searchParams;
}

/** Reads the body from a clone, so the request can still be read by the test afterwards. */
export function bodyOf<T = Record<string, unknown>>(request: Request): Promise<T> {
  return request.clone().json() as Promise<T>;
}

/** A calendar day, YYYY-MM-DD, `offset` days from today in the user's zone (Moscow). */
export function dayFromToday(offset: number): string {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
  const [year = 0, month = 1, day = 1] = today.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + offset)).toISOString().slice(0, 10);
}

export function renderApp(route: string) {
  const client = new QueryClient({
    queryCache: new QueryCache(),
    defaultOptions: { queries: { retry: false } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

export function makeBoard(overrides: Partial<Board> = {}): Board {
  return {
    id: crypto.randomUUID(),
    name: "Доска",
    description: null,
    icon: "list-checks",
    default_view: "list",
    is_default: false,
    is_shared: false,
    my_role: "owner",
    members: [USER_SUMMARY],
    open_tasks_count: 0,
    archived_at: null,
    version: 1,
    ...overrides,
  };
}

export function makeColumn(overrides: Partial<BoardColumn> = {}): BoardColumn {
  return {
    id: crypto.randomUUID(),
    name: "Колонка",
    position: "a",
    is_done: false,
    task_count: 0,
    ...overrides,
  };
}

export function makeTask(overrides: Partial<Task> = {}): Task {
  const checklist = overrides.checklist ?? [];
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    board_id: crypto.randomUUID(),
    board_name: "Доска",
    column_id: crypto.randomUUID(),
    title: "Задача",
    priority: 3,
    position: "a",
    start_date: null,
    due_date: null,
    due_at: null,
    completed_at: null,
    assignees: [],
    checklist_total: checklist.length,
    checklist_done: checklist.filter((item) => item.is_done).length,
    updated_at: now,
    description: null,
    checklist,
    created_by: USER_SUMMARY,
    version: 1,
    created_at: now,
    ...overrides,
  };
}

export function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: crypto.randomUUID(),
    kind: "task_assigned",
    title: "Задача",
    actor: null,
    task_id: null,
    board_id: null,
    data: {},
    created_at: new Date().toISOString(),
    read_at: null,
    ...overrides,
  };
}

export type AppStub = {
  boards?: Board[];
  columns?: BoardColumn[];
  tasks?: Task[];
  notifications?: Notification[];
  sync?: SyncState;
  /** Runs before the GET routes, a Response it returns is the answer. */
  onRequest?: Stub;
};

type AppData = Required<Omit<AppStub, "onRequest">>;

function notFound(): Response {
  return apiError(404, "not_found", "Не найдено");
}

function unhandled(request: Request): Response {
  return apiError(404, "not_found", `Нет заглушки: ${request.method} ${path(request)}`);
}

function route(request: Request): string {
  return path(request).replace(`${API}/`, "");
}

function usersOf(boards: Board[]): UserSummary[] {
  const users = new Map<string, UserSummary>([[USER.id, USER_SUMMARY]]);
  for (const board of boards) {
    for (const user of board.members) users.set(user.id, user);
  }
  return [...users.values()];
}

function boardRoute(
  request: Request,
  data: AppData,
  id: string | undefined,
  child: string | undefined,
) {
  if (id === undefined) {
    const archived = searchOf(request).get("archived") === "true";
    return json(200, {
      items: data.boards.filter((board) => (board.archived_at !== null) === archived),
    });
  }
  const board = data.boards.find((item) => item.id === id);
  if (!board) return notFound();
  if (child === undefined) return json(200, board);
  if (child === "columns") return json(200, { items: data.columns });
  if (child === "members") {
    // The current user keeps the role the board gives them, other members are editors.
    const items = board.members.map((user) => ({
      user,
      role: user.id === USER.id ? board.my_role : "editor",
    }));
    return json(200, { items });
  }
  return unhandled(request);
}

function taskRoute(
  request: Request,
  data: AppData,
  id: string | undefined,
  child: string | undefined,
) {
  if (child !== undefined) return unhandled(request);
  if (id === undefined) {
    const params = searchOf(request);
    const column = params.get("column_id");
    const status = params.get("status") ?? "all";
    const items = data.tasks.filter(
      (task) =>
        (!column || task.column_id === column) &&
        (status === "all" ||
          (status === "open" && task.completed_at === null) ||
          (status === "done" && task.completed_at !== null)),
    );
    return json(200, { items, next_cursor: null });
  }
  const task = data.tasks.find((item) => item.id === id);
  return task ? json(200, task) : notFound();
}

function answer(request: Request, data: AppData): Response {
  if (request.method !== "GET") return unhandled(request);
  const [resource, id, child] = route(request).split("/");
  switch (resource) {
    case "me":
      return json(200, USER);
    case "sync":
      return json(200, data.sync);
    case "users":
      return json(200, { items: usersOf(data.boards) });
    case "boards":
      return boardRoute(request, data, id, child);
    case "tasks":
      return taskRoute(request, data, id, child);
    case "notifications":
      return json(200, { items: data.notifications, next_cursor: null });
    default:
      return unhandled(request);
  }
}

/**
 * Answers the GET routes of the app from the given data. The arrays and the sync object are read
 * on every request, so a test can change them between two refetches. Returns the requests seen.
 */
export function stubApp({
  boards = [],
  columns = [],
  tasks = [],
  notifications = [],
  sync = { calendar: 0, tasks: 0, notifications: 0, unread_notifications: 0 },
  onRequest,
}: AppStub = {}): Request[] {
  return stubBackend(async (request) => {
    const override = await onRequest?.(request);
    if (override) return override;
    return answer(request, { boards, columns, tasks, notifications, sync });
  });
}
