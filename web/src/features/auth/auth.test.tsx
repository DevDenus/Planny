import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { queryClient as sharedClient, ME_KEY } from "../../api/queryClient";
import { App } from "../../App";
import { loginErrorMessage } from "./LoginPage";
import { validateNewPassword } from "./password";

const USER = {
  id: "1",
  display_name: "Саша",
  color: "teal",
  login: "sasha",
  timezone: "Europe/Moscow",
  must_change_password: false,
};

type Stub = (request: Request) => Response | undefined;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(status: number, code: string, message: string, details = {}): Response {
  return json(status, { error: { code, message, details, request_id: "r" } });
}

const UNAUTHORIZED = () => apiError(401, "unauthorized", "Требуется вход");

function stubBackend(stub: Stub) {
  const calls: Request[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo, init?: RequestInit) => {
    const request = new Request(new URL(input as string, "http://localhost"), init);
    const real = input instanceof Request ? input : request;
    calls.push(real);
    return Promise.resolve(stub(real) ?? UNAUTHORIZED());
  });
  return calls;
}

function path(request: Request): string {
  return new URL(request.url).pathname;
}

function renderApp(route: string) {
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

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

describe("session guard", () => {
  it("sends an anonymous visitor to the login screen", async () => {
    stubBackend(() => undefined);
    renderApp("/calendar");
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
  });

  it("shows the app to a signed-in user", async () => {
    stubBackend((request) => (path(request).endsWith("/me") ? json(200, USER) : undefined));
    renderApp("/calendar");
    expect(await screen.findByRole("radiogroup", { name: "Вид" })).toBeInTheDocument();
  });

  it("forces the password change and does not let the user past it", async () => {
    stubBackend((request) =>
      path(request).endsWith("/me")
        ? json(200, { ...USER, must_change_password: true })
        : undefined,
    );
    renderApp("/tasks");
    expect(await screen.findByRole("heading", { name: "Смена пароля" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Задачи" })).not.toBeInTheDocument();
  });

  it("leaves the password screen when no change is due", async () => {
    stubBackend((request) => (path(request).endsWith("/me") ? json(200, USER) : undefined));
    renderApp("/change-password");
    expect(await screen.findByRole("radiogroup", { name: "Вид" })).toBeInTheDocument();
  });

  it("offers a retry when the server fails instead of treating it as signed out", async () => {
    stubBackend(() => apiError(502, "upstream_unavailable", "Сервер временно недоступен"));
    renderApp("/calendar");
    expect(await screen.findByRole("button", { name: "Повторить" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Вход" })).not.toBeInTheDocument();
  });

  it("shows the login form when the session ends while the app is open", async () => {
    let alive = true;
    stubBackend((request) =>
      alive && path(request).endsWith("/me") ? json(200, USER) : undefined,
    );
    const { client } = renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Настройки" })).toBeInTheDocument();

    alive = false;
    await client.invalidateQueries({ queryKey: ME_KEY });

    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.getByLabelText("Логин")).toBeInTheDocument();
    expect(screen.getByText("Сеанс завершён, войдите снова")).toBeInTheDocument();
  });

  it("says nothing about a session to someone who opens the site signed out", async () => {
    stubBackend(() => undefined);
    renderApp("/settings");

    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.queryByText("Сеанс завершён, войдите снова")).not.toBeInTheDocument();
  });

  it("returns to the same screen and dialog after signing in again", async () => {
    let alive = true;
    stubBackend((request) => {
      if (path(request) === "/bff/login") {
        alive = true;
        return json(200, { user: USER, csrf_token: "c" });
      }
      return alive && path(request).endsWith("/me") ? json(200, USER) : undefined;
    });
    const { client } = renderApp("/settings?task=t1");
    expect(await screen.findByRole("heading", { name: "Настройки" })).toBeInTheDocument();

    alive = false;
    await client.invalidateQueries({ queryKey: ME_KEY });
    await screen.findByRole("heading", { name: "Вход" });

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Логин"), "sasha");
    await user.type(screen.getByLabelText("Пароль", { exact: true }), "family-planner-2026");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("heading", { name: "Настройки" })).toBeInTheDocument();
    expect(await screen.findByRole("dialog", { name: "Задача" })).toBeInTheDocument();
  });

  it("signs in again after the session ended", async () => {
    let alive = true;
    stubBackend((request) => {
      if (path(request) === "/bff/login") {
        alive = true;
        return json(200, { user: USER });
      }
      return alive && path(request).endsWith("/me") ? json(200, USER) : undefined;
    });
    const { client } = renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Настройки" })).toBeInTheDocument();

    alive = false;
    await client.invalidateQueries({ queryKey: ME_KEY });
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Логин"), "sasha");
    await user.type(screen.getByLabelText("Пароль"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("heading", { name: "Настройки" })).toBeInTheDocument();
  });
});

describe("login", () => {
  it("signs in and returns to the requested page", async () => {
    let signedIn = false;
    const calls = stubBackend((request) => {
      if (path(request) === "/bff/login") {
        signedIn = true;
        return json(200, { user: USER });
      }
      return path(request).endsWith("/me") && signedIn ? json(200, USER) : undefined;
    });
    renderApp("/tasks");

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Логин"), "sasha");
    await user.type(screen.getByLabelText("Пароль"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("heading", { name: "Задачи" })).toBeInTheDocument();
    const login = calls.find((request) => path(request) === "/bff/login")!;
    expect(login.method).toBe("POST");
  });

  it("shows the server message on wrong credentials", async () => {
    stubBackend((request) =>
      path(request) === "/bff/login"
        ? apiError(401, "unauthorized", "Неверный логин или пароль")
        : undefined,
    );
    renderApp("/login");

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Логин"), "sasha");
    await user.type(screen.getByLabelText("Пароль"), "wrong");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль");
  });

  it("states the wait in whole minutes when rate limited", () => {
    const error = new ApiError(429, "rate_limited", "x", { retry_after: 61 });
    expect(loginErrorMessage(error)).toBe("Слишком много попыток. Повторите через 2 мин");
  });
});

describe("forced password change", () => {
  const FORCED = { ...USER, must_change_password: true };

  it("checks the form before calling the server and focuses the bad field", async () => {
    const calls = stubBackend((request) =>
      path(request).endsWith("/me") ? json(200, FORCED) : undefined,
    );
    renderApp("/change-password");

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Новый пароль"), "short");
    await user.click(screen.getByRole("button", { name: "Сохранить пароль" }));

    expect(await screen.findByText("Минимум 8 символов")).toBeInTheDocument();
    expect(screen.getByLabelText("Новый пароль")).toHaveFocus();
    expect(calls.some((request) => path(request).endsWith("/change-password"))).toBe(false);
  });

  it("sends the new password with the CSRF token and opens the app", async () => {
    document.cookie = "planny_csrf=csrf-value";
    let changed = false;
    const calls = stubBackend((request) => {
      if (path(request).endsWith("/change-password")) {
        changed = true;
        return new Response(null, { status: 204 });
      }
      return path(request).endsWith("/me") ? json(200, changed ? USER : FORCED) : undefined;
    });
    renderApp("/change-password");

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Новый пароль"), "a-long-password");
    await user.type(screen.getByLabelText("Повторите пароль"), "a-long-password");
    await user.click(screen.getByRole("button", { name: "Сохранить пароль" }));

    expect(await screen.findByRole("radiogroup", { name: "Вид" })).toBeInTheDocument();
    const change = calls.find((request) => path(request).endsWith("/change-password"))!;
    expect(change.headers.get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("validates length and repetition", () => {
    expect(validateNewPassword("short", "short").password).toBeDefined();
    expect(validateNewPassword("long-enough", "different").repeat).toBeDefined();
    expect(validateNewPassword("long-enough", "long-enough")).toEqual({});
  });
});

describe("shared query client", () => {
  it("does not recheck the session after its own failure, so it can't loop", async () => {
    const invalidate = vi.spyOn(sharedClient, "invalidateQueries");
    stubBackend(() => undefined);

    await sharedClient
      .fetchQuery({
        queryKey: ME_KEY,
        retry: false,
        queryFn: () => Promise.reject(new ApiError(401, "unauthorized", "x")),
      })
      .catch(() => undefined);

    await waitFor(() => expect(invalidate).not.toHaveBeenCalled());
    sharedClient.clear();
  });

  it("rechecks the session when another request learns it has ended", async () => {
    const invalidate = vi.spyOn(sharedClient, "invalidateQueries");
    invalidate.mockClear();

    await sharedClient
      .fetchQuery({
        queryKey: ["tasks"],
        retry: false,
        queryFn: () => Promise.reject(new ApiError(401, "unauthorized", "x")),
      })
      .catch(() => undefined);

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ME_KEY });
    sharedClient.clear();
  });
});
