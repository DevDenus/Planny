import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventSummary } from "../../api/client";
import { API, apiError, makeTask, path, requestsTo, searchOf, stubApp } from "../tasks/testing";
import { SearchBox, SearchButton } from "./SearchBox";

const SEARCH = `${API}/search`;

/** On 2026-11-06 at 19:00 in Moscow. */
const LAUNCH: EventSummary = {
  id: "e1",
  title: "Ужин вдвоём",
  all_day: false,
  start_at: "2026-11-06T16:00:00Z",
  start_date: null,
  is_recurring: false,
  next_occurrence_start: null,
};

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

/** Shows the query string of the URL, so a test can see where a choice led. */
function LocationProbe() {
  const { search } = useLocation();
  return <output aria-label="Адрес">{search}</output>;
}

function renderSearch(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/calendar"]}>
        {ui}
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function input(): HTMLElement {
  return screen.getByRole("searchbox", { name: "Поиск" });
}

describe("search box", () => {
  it("shows the matching events and tasks in two sections, with their dates and boards", async () => {
    stubApp({
      searchResults: {
        events: [LAUNCH],
        tasks: [makeTask({ id: "t1", title: "Купить продукты", board_name: "Дом" })],
      },
    });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");

    expect(await screen.findByRole("heading", { name: "События" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Задачи" })).toBeInTheDocument();
    const event = screen.getByRole("button", { name: /Ужин вдвоём/ });
    // The time is shown in the zone of the user, which arrives with /me.
    await waitFor(() => expect(event).toHaveTextContent("Пт, 6 ноября, 19:00"));
    expect(screen.getByRole("button", { name: /Купить продукты/ })).toHaveTextContent("Дом");
  });

  it("shows the next repeat of a found series, and only the day for an all-day one", async () => {
    stubApp({
      searchResults: {
        events: [
          {
            ...LAUNCH,
            is_recurring: true,
            next_occurrence_start: "2026-11-13T16:00:00Z",
          },
          {
            id: "e2",
            title: "Ужин на даче",
            all_day: true,
            start_at: null,
            start_date: "2026-11-06",
            is_recurring: true,
            next_occurrence_start: "2026-11-09",
          },
        ],
        tasks: [],
      },
    });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");

    const series = await screen.findByRole("button", { name: /Ужин вдвоём/ });
    // The time is shown in the zone of the user, which arrives with /me.
    await waitFor(() => expect(series).toHaveTextContent("Пт, 13 ноября, 19:00"));
    expect(screen.getByRole("button", { name: /Ужин на даче/ })).toHaveTextContent("Пн, 9 ноября");
  });

  it("sends no request and shows no dropdown for blank text", async () => {
    const calls = stubApp({ searchResults: { events: [LAUNCH], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "   ");
    // Longer than the debounce, so a request would have gone out by now.
    await new Promise((resolve) => setTimeout(resolve, 300));

    expect(requestsTo(calls, "GET", SEARCH)).toHaveLength(0);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("asks the server once, after the pause, for the trimmed text", async () => {
    const calls = stubApp({ searchResults: { events: [], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "  Ужин  ");
    expect(await screen.findByText("Ничего не найдено")).toBeInTheDocument();

    const requests = requestsTo(calls, "GET", SEARCH);
    expect(requests).toHaveLength(1);
    expect(searchOf(requests[0]!).get("q")).toBe("Ужин");
  });

  it("says that nothing was found when neither section has a match", async () => {
    stubApp({ searchResults: { events: [], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "зз");

    expect(await screen.findByText("Ничего не найдено")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "События" })).not.toBeInTheDocument();
  });

  it("says that the search failed when the server does not answer", async () => {
    stubApp({
      onRequest: (request) =>
        request.method === "GET" && path(request) === SEARCH
          ? apiError(500, "internal", "Ошибка")
          : undefined,
    });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");

    expect(await screen.findByText("Не удалось выполнить поиск")).toBeInTheDocument();
  });

  it("opens the event in the URL, clears the text and closes the results when it is chosen", async () => {
    stubApp({ searchResults: { events: [LAUNCH], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");
    await user.click(await screen.findByRole("button", { name: /Ужин вдвоём/ }));

    expect(screen.getByLabelText("Адрес")).toHaveTextContent("?event=e1");
    expect(input()).toHaveValue("");
    expect(screen.queryByRole("heading", { name: "События" })).not.toBeInTheDocument();
  });

  it("closes the dropdown on Escape and opens it again when typing", async () => {
    stubApp({ searchResults: { events: [LAUNCH], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");
    expect(await screen.findByRole("heading", { name: "События" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: "События" })).not.toBeInTheDocument();

    await user.type(input(), "!");
    expect(await screen.findByRole("heading", { name: "События" })).toBeInTheDocument();
  });

  it("closes the dropdown on a click outside it", async () => {
    stubApp({ searchResults: { events: [LAUNCH], tasks: [] } });
    renderSearch(<SearchBox />);

    const user = userEvent.setup();
    await user.type(input(), "ужин");
    expect(await screen.findByRole("heading", { name: "События" })).toBeInTheDocument();

    await user.click(document.body);
    expect(screen.queryByRole("heading", { name: "События" })).not.toBeInTheDocument();
  });
});

describe("search button", () => {
  it("opens the same search in a dialog, and closes the dialog after a choice", async () => {
    stubApp({ searchResults: { events: [LAUNCH], tasks: [] } });
    renderSearch(<SearchButton />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Поиск" }));
    const dialog = await screen.findByRole("dialog", { name: "Поиск" });
    await user.type(within(dialog).getByRole("searchbox", { name: "Поиск" }), "ужин");
    await user.click(await within(dialog).findByRole("button", { name: /Ужин вдвоём/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Адрес")).toHaveTextContent("?event=e1");
  });
});
