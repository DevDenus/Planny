import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../ui";
import {
  API,
  apiError,
  bodyOf,
  json,
  makeCategory,
  path,
  requestsTo,
  stubApp,
} from "../tasks/testing";
import { CategoriesSection } from "./CategoriesSection";

const CATEGORIES = `${API}/categories`;
const BLANK_NAME = "Введите название";
const DUPLICATE = "Категория с таким названием уже есть";

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ToastProvider>
          <CategoriesSection />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("categories", () => {
  it("lists each category with its name and colour", async () => {
    stubApp({
      categories: [
        makeCategory({ id: "c1", name: "Личное", color: "violet" }),
        makeCategory({ id: "c2", name: "Работа", color: "blue", position: 1 }),
      ],
    });
    renderSection();

    expect(await screen.findByDisplayValue("Личное")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Работа")).toBeInTheDocument();
    const [first, second] = screen.getAllByRole("combobox", { name: "Цвет" });
    expect(first).toHaveValue("violet");
    expect(second).toHaveValue("blue");
  });

  it("adds a category with POST and shows it in the list", async () => {
    const categories = [makeCategory({ id: "c1", name: "Личное", color: "violet" })];
    const created = makeCategory({ id: "c2", name: "Работа", color: "blue", position: 1 });
    const calls = stubApp({
      categories,
      onRequest: (request) => {
        if (request.method !== "POST" || path(request) !== CATEGORIES) return undefined;
        categories.push(created);
        return json(201, created);
      },
    });
    renderSection();

    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Новая категория" }), "Работа");
    await user.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() => expect(requestsTo(calls, "POST", CATEGORIES)).toHaveLength(1));
    const [post] = requestsTo(calls, "POST", CATEGORIES);
    // The first colour that no category uses yet is the default.
    expect(await bodyOf(post!)).toEqual({ name: "Работа", color: "blue" });
    expect(await screen.findByDisplayValue("Работа")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Новая категория" })).toHaveValue("");
  });

  it("shows the server's message under the name when the name is taken", async () => {
    stubApp({
      categories: [makeCategory({ id: "c1", name: "Личное" })],
      onRequest: (request) =>
        request.method === "POST" && path(request) === CATEGORIES
          ? apiError(422, "validation_error", "Ошибка в данных", {
              fields: { name: DUPLICATE },
            })
          : undefined,
    });
    renderSection();

    const user = userEvent.setup();
    const field = await screen.findByRole("textbox", { name: "Новая категория" });
    await user.type(field, "Личное");
    await user.click(screen.getByRole("button", { name: "Добавить" }));

    expect(await screen.findByText(DUPLICATE)).toBeInTheDocument();
    expect(field).toHaveAccessibleDescription(DUPLICATE);
  });

  it("asks for a name and sends nothing when the new name is blank", async () => {
    const calls = stubApp({ categories: [makeCategory({ name: "Личное" })] });
    renderSection();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Добавить" }));

    expect(await screen.findByText(BLANK_NAME)).toBeInTheDocument();
    expect(requestsTo(calls, "POST", CATEGORIES)).toHaveLength(0);
  });

  it("renames a category on blur, and sends nothing when the name is unchanged", async () => {
    const personal = makeCategory({ id: "c1", name: "Личное", color: "violet" });
    const work = makeCategory({ id: "c2", name: "Работа", color: "blue", position: 1 });
    const calls = stubApp({
      categories: [personal, work],
      onRequest: (request) => {
        if (request.method !== "PATCH" || path(request) !== `${CATEGORIES}/c1`) return undefined;
        personal.name = "Семья";
        return json(200, personal);
      },
    });
    renderSection();

    const user = userEvent.setup();
    const personalField = await screen.findByDisplayValue("Личное");
    await user.clear(personalField);
    await user.type(personalField, "Семья");
    await user.tab();

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${CATEGORIES}/c1`)).toHaveLength(1));
    const [patch] = requestsTo(calls, "PATCH", `${CATEGORIES}/c1`);
    expect(await bodyOf(patch!)).toEqual({ name: "Семья" });

    // Focusing the other name and leaving it unchanged sends nothing.
    await user.click(screen.getByDisplayValue("Работа"));
    await user.tab();
    expect(requestsTo(calls, "PATCH", `${CATEGORIES}/c2`)).toHaveLength(0);
  });

  it("saves a name on Enter", async () => {
    const personal = makeCategory({ id: "c1", name: "Личное" });
    const calls = stubApp({
      categories: [personal],
      onRequest: (request) => {
        if (request.method !== "PATCH" || path(request) !== `${CATEGORIES}/c1`) return undefined;
        personal.name = "Дом";
        return json(200, personal);
      },
    });
    renderSection();

    const user = userEvent.setup();
    const field = await screen.findByDisplayValue("Личное");
    await user.clear(field);
    await user.type(field, "Дом{Enter}");

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${CATEGORIES}/c1`)).toHaveLength(1));
    const [patch] = requestsTo(calls, "PATCH", `${CATEGORIES}/c1`);
    expect(await bodyOf(patch!)).toEqual({ name: "Дом" });
  });

  it("returns a blank name to the saved name and sends nothing", async () => {
    const calls = stubApp({ categories: [makeCategory({ id: "c1", name: "Личное" })] });
    renderSection();

    const user = userEvent.setup();
    const field = await screen.findByDisplayValue("Личное");
    await user.clear(field);
    await user.tab();

    expect(field).toHaveValue("Личное");
    expect(requestsTo(calls, "PATCH", `${CATEGORIES}/c1`)).toHaveLength(0);
  });

  it("saves a colour at once on change", async () => {
    const personal = makeCategory({ id: "c1", name: "Личное", color: "violet" });
    const calls = stubApp({
      categories: [personal],
      onRequest: (request) => {
        if (request.method !== "PATCH" || path(request) !== `${CATEGORIES}/c1`) return undefined;
        personal.color = "teal";
        return json(200, personal);
      },
    });
    renderSection();

    const user = userEvent.setup();
    const [select] = await screen.findAllByRole("combobox", { name: "Цвет" });
    await user.selectOptions(select!, "teal");

    await waitFor(() => expect(requestsTo(calls, "PATCH", `${CATEGORIES}/c1`)).toHaveLength(1));
    const [patch] = requestsTo(calls, "PATCH", `${CATEGORIES}/c1`);
    expect(await bodyOf(patch!)).toEqual({ color: "teal" });
  });

  it("asks before deleting, and deletes once confirmed", async () => {
    const personal = makeCategory({ id: "c1", name: "Личное" });
    const categories = [personal];
    const calls = stubApp({
      categories,
      onRequest: (request) => {
        if (request.method !== "DELETE" || path(request) !== `${CATEGORIES}/c1`) return undefined;
        categories.splice(categories.indexOf(personal), 1);
        return new Response(null, { status: 204 });
      },
    });
    renderSection();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Удалить категорию Личное" }));
    const dialog = await screen.findByRole("dialog", { name: "Удалить категорию?" });
    expect(
      within(dialog).getByText("События останутся, у них просто пропадёт эта категория."),
    ).toBeInTheDocument();
    expect(requestsTo(calls, "DELETE", `${CATEGORIES}/c1`)).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(requestsTo(calls, "DELETE", `${CATEGORIES}/c1`)).toHaveLength(1));
    await waitFor(() => expect(screen.queryByDisplayValue("Личное")).not.toBeInTheDocument());
  });

  it("sends nothing when the deletion is cancelled", async () => {
    const calls = stubApp({ categories: [makeCategory({ id: "c1", name: "Личное" })] });
    renderSection();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Удалить категорию Личное" }));
    const dialog = await screen.findByRole("dialog", { name: "Удалить категорию?" });
    await user.click(within(dialog).getByRole("button", { name: "Отмена" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestsTo(calls, "DELETE", `${CATEGORIES}/c1`)).toHaveLength(0);
  });

  it("shows a banner when the list cannot be loaded", async () => {
    stubApp({
      onRequest: (request) =>
        request.method === "GET" && path(request) === CATEGORIES
          ? apiError(500, "internal", "Ошибка")
          : undefined,
    });
    renderSection();

    expect(await screen.findByText("Не удалось загрузить категории")).toBeInTheDocument();
  });
});
