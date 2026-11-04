import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME_KEY } from "../../api/queryClient";
import {
  API,
  apiError,
  json,
  makeBoard,
  makeTask,
  path,
  renderApp,
  requestsTo,
  stubApp,
  USER,
} from "../tasks/testing";

describe("the next person at this browser", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  it("sees nothing of the previous account when a session ended without a logout", async () => {
    const OTHER = { ...USER, id: "u2", display_name: "Женя" };
    let account: "first" | "expired" | "second" = "first";
    const personal = makeBoard({ is_default: true, name: "Личная доска" });
    const calls = stubApp({
      boards: [personal],
      tasks: [makeTask({ board_id: personal.id, title: "Секрет Саши" })],
      onRequest: (request) => {
        const url = path(request);
        if (url === "/bff/login") {
          account = "second";
          return new Response(null, { status: 204 });
        }
        if (url === `${API}/me`) {
          if (account === "expired") return apiError(401, "unauthorized", "Требуется вход");
          return json(200, account === "first" ? USER : OTHER);
        }
        if (account === "second" && url === `${API}/boards`) return json(200, { items: [] });
        if (account === "second" && url === `${API}/tasks`) {
          return json(200, { items: [], next_cursor: null });
        }
        return undefined;
      },
    });
    const { client } = renderApp("/tasks");
    // As fresh as the app keeps it: no refetch on mount would hide the leak.
    client.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
    await screen.findByText("Секрет Саши");
    const requestsBefore = requestsTo(calls, "GET", `${API}/tasks`).length;

    account = "expired";
    await act(async () => {
      await client.invalidateQueries({ queryKey: ME_KEY });
    });
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Логин" }), "zhenya");
    await user.type(screen.getByLabelText("Пароль"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    await screen.findByText("Женя");
    await waitFor(() =>
      expect(requestsTo(calls, "GET", `${API}/tasks`).length).toBeGreaterThan(requestsBefore),
    );
    expect(screen.queryByText("Секрет Саши")).not.toBeInTheDocument();
  });
});
