import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type CurrentUser = components["schemas"]["CurrentUser"];

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
