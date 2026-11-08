import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type CurrentUser = Schemas["CurrentUser"];
export type UserSummary = Schemas["UserSummary"];
export type Board = Schemas["Board"];
export type BoardColumn = Schemas["BoardColumn"];
export type BoardRole = Board["my_role"];
export type Task = Schemas["Task"];
export type TaskSummary = Schemas["TaskSummary"];
export type TaskCreate = Schemas["TaskCreate"];
export type TaskUpdate = Schemas["TaskUpdate"];
export type TaskPage = Schemas["TaskPage"];
export type TaskFilters = NonNullable<paths["/api/v1/tasks"]["get"]["parameters"]["query"]>;
export type ChecklistItem = Schemas["ChecklistItem"];
export type Label = Schemas["Label"];
export type LabelColor = Label["color"];
export type TaskComment = Schemas["TaskComment"];
export type TaskCommentPage = Schemas["TaskCommentPage"];
export type TaskActivity = Schemas["TaskActivity"];
export type TaskActivityPage = Schemas["TaskActivityPage"];
export type Notification = Schemas["Notification"];
export type SyncState = Schemas["SyncState"];
export type Category = Schemas["Category"];
export type CategoryColor = Category["color"];
export type CategoryCreate = Schemas["CategoryCreate"];
export type CategoryUpdate = Schemas["CategoryUpdate"];
/** "Event" alone would hide the DOM type of the same name. */
export type CalendarEvent = Schemas["Event"];
export type EventCreate = Schemas["EventCreate"];
export type EventUpdate = Schemas["EventUpdate"];
export type EventSummary = Schemas["EventSummary"];
export type EventOccurrence = Schemas["EventOccurrence"];
export type TaskDeadline = Schemas["TaskDeadline"];
export type CalendarItem = EventOccurrence | TaskDeadline;
export type BusyInterval = Schemas["BusyInterval"];
export type UserAvailability = Schemas["UserAvailability"];
export type SearchResults = Schemas["SearchResults"];
export type AssistantStatus = Schemas["AssistantStatus"];
export type AssistantChat = Schemas["Chat"];
export type AssistantChatSummary = Schemas["ChatSummary"];
export type AssistantMessage = Schemas["Message"];
export type AssistantCard = NonNullable<AssistantChat["card"]>;
export type TaskCard = Schemas["TaskCard"];
export type EventCard = Schemas["EventCard"];

interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id: string;
  };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Validation messages by field name. */
  get fields(): Record<string, string> {
    return (this.details.fields as Record<string, string> | undefined) ?? {};
  }
}

const CSRF_COOKIE = /(?:^|;\s*)(?:__Host-)?planny_csrf=([^;]+)/;
const SAFE_METHODS = new Set(["GET", "HEAD"]);

function csrfToken(): string | undefined {
  return CSRF_COOKIE.exec(document.cookie)?.[1];
}

async function bffFetch(input: Request): Promise<Response> {
  if (!SAFE_METHODS.has(input.method)) {
    const token = csrfToken();
    if (token) input.headers.set("X-CSRF-Token", token);
  }
  return fetch(input);
}

export const api = createClient<paths>({
  baseUrl: `${window.location.origin}/bff`,
  fetch: bffFetch,
  credentials: "same-origin",
});

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const { error } = (await response.json()) as ApiErrorBody;
    return new ApiError(response.status, error.code, error.message, error.details);
  } catch {
    return new ApiError(response.status, "unknown", "Сервер не ответил. Попробуйте ещё раз");
  }
}

interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Turns an openapi-fetch result into a value or a thrown ApiError. */
export async function unwrap<T>(result: Promise<ApiResult<T>>): Promise<T> {
  const { data, error, response } = await result;
  if (error !== undefined || !response.ok) {
    const failure = error as ApiErrorBody | undefined;
    if (failure?.error) {
      const { code, message, details } = failure.error;
      throw new ApiError(response.status, code, message, details);
    }
    throw await toApiError(response);
  }
  return data as T;
}

export async function login(credentials: { login: string; password: string }): Promise<void> {
  const response = await fetch("/bff/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(credentials),
  });
  if (!response.ok) throw await toApiError(response);
}

export async function logout(): Promise<void> {
  const token = csrfToken();
  const response = await fetch("/bff/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: token ? { "X-CSRF-Token": token } : {},
  });
  if (!response.ok) throw await toApiError(response);
}
