import { expect, test, type Page, type Route } from "@playwright/test";

import { addCard, cardOf, changePasswordElsewhere, kanbanBoard, signIn } from "./support";

const SERVER_ERROR = {
  status: 500,
  json: { error: { code: "internal_error", message: "Внутренняя ошибка", details: {} } },
};
const NO_CONNECTION = "Нет связи с сервером";

const taskDialog = (page: Page) => page.getByRole("dialog", { name: "Задача", exact: true });

test("сессия заканчивается при открытой вкладке, вход возвращает к той же задаче", async ({
  browser,
}, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  const board = await kanbanBoard(user, "Дом");
  const card = await addCard(user, board.id, board.todo.id, "Хлеб");
  await user.page.goto(`/boards/${board.id}?task=${card.id}`);
  await expect(taskDialog(user.page).getByLabel("Название")).toHaveValue("Хлеб");

  const newPassword = "another-family-password";
  await changePasswordElsewhere(browser, user, newPassword);

  await expect(user.page.getByText("Сеанс завершён, войдите снова")).toBeVisible();
  await expect(user.page).toHaveURL(/\/login$/);
  await user.page.getByLabel("Логин").fill(user.login);
  await user.page.getByLabel("Пароль", { exact: true }).fill(newPassword);
  await user.page.getByRole("button", { name: "Войти" }).click();

  await expect(user.page).toHaveURL(new RegExp(`/boards/${board.id}\\?task=${card.id}$`));
  await expect(taskDialog(user.page).getByLabel("Название")).toHaveValue("Хлеб");
});

test("без связи данные остаются на экране, а полоса уходит вместе с обрывом", async ({
  browser,
}, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  const board = await kanbanBoard(user, "Дом");
  await addCard(user, board.id, board.todo.id, "Хлеб");
  await user.page.goto(`/boards/${board.id}`);
  await expect(cardOf(user.page, "Хлеб")).toBeVisible();

  await user.page.route("**/bff/api/**", (route) => route.abort());
  await expect(user.page.getByText(NO_CONNECTION)).toBeVisible({ timeout: 20_000 });
  await expect(cardOf(user.page, "Хлеб")).toBeVisible();

  await user.page.unroute("**/bff/api/**");
  await expect(user.page.getByText(NO_CONNECTION)).toBeHidden({ timeout: 20_000 });
});

test("ошибка загрузки показывает «Повторить», и повтор загружает данные", async ({
  browser,
}, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  await kanbanBoard(user, "Дом");
  const list = /\/bff\/api\/v1\/boards(\?.*)?$/;
  await user.page.route(list, (route) => route.fulfill(SERVER_ERROR));

  await user.page.goto("/boards");
  await expect(user.page.getByText("Не удалось загрузить доски")).toBeVisible();

  await user.page.unroute(list);
  await user.page.getByRole("button", { name: "Повторить" }).click();
  await expect(user.page.getByRole("link", { name: /Дом/ }).first()).toBeVisible();
});

test("ошибка сохранения оставляет форму открытой с введёнными данными", async ({
  browser,
}, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  const board = await kanbanBoard(user, "Дом");
  const card = await addCard(user, board.id, board.todo.id, "Хлеб");
  await user.page.goto(`/boards/${board.id}?task=${card.id}`);
  const dialog = taskDialog(user.page);
  await dialog.getByLabel("Название").fill("Батон");

  const failSaving = (route: Route) =>
    route.request().method() === "PATCH" ? route.fulfill(SERVER_ERROR) : route.continue();
  await user.page.route(`**/bff/api/v1/tasks/${card.id}`, failSaving);
  await dialog.getByRole("button", { name: "Сохранить" }).click();

  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByLabel("Название")).toHaveValue("Батон");

  await user.page.unroute(`**/bff/api/v1/tasks/${card.id}`);
  await dialog.getByRole("button", { name: "Сохранить" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(cardOf(user.page, "Батон")).toBeVisible();
});

test("конфликт версий спрашивает, что делать, и не теряет введённое", async ({
  browser,
}, testInfo) => {
  const owner = await signIn(browser, "Саша", { ...testInfo.project.use });
  const helper = await signIn(browser, "Женя", { ...testInfo.project.use });
  const board = await kanbanBoard(owner, "Дом");
  await owner.api("POST", `boards/${board.id}/members`, { user_id: helper.id, role: "editor" });
  const card = await addCard(owner, board.id, board.todo.id, "Хлеб");

  await helper.page.goto(`/boards/${board.id}?task=${card.id}`);
  const dialog = taskDialog(helper.page);
  await dialog.getByLabel("Название").fill("Батон");
  await owner.api("PATCH", `tasks/${card.id}`, { title: "Булка", version: card.version });

  await dialog.getByRole("button", { name: "Сохранить" }).click();
  const conflict = helper.page.getByRole("dialog", {
    name: "Объект изменился, пока вы его редактировали",
  });
  await expect(conflict.getByText(/Последнее изменение: Саша/)).toBeVisible();
  await conflict.getByRole("button", { name: "Сохранить мои изменения" }).click();

  await expect(dialog).toHaveCount(0);
  const saved = await owner.api<{ title: string }>("GET", `tasks/${card.id}`);
  expect(saved.title).toBe("Батон");
});

test("задачу удалили, пока форма открыта: её можно создать заново", async ({
  browser,
}, testInfo) => {
  const owner = await signIn(browser, "Саша", { ...testInfo.project.use });
  const helper = await signIn(browser, "Женя", { ...testInfo.project.use });
  const board = await kanbanBoard(owner, "Дом");
  await owner.api("POST", `boards/${board.id}/members`, { user_id: helper.id, role: "editor" });
  const card = await addCard(owner, board.id, board.todo.id, "Хлеб");

  await helper.page.goto(`/boards/${board.id}?task=${card.id}`);
  const dialog = taskDialog(helper.page);
  await dialog.getByLabel("Название").fill("Батон");
  await owner.api("DELETE", `tasks/${card.id}`);

  await expect(dialog.getByText("Задачу удалили, пока вы её редактировали.")).toBeVisible();
  await expect(dialog.getByLabel("Название")).toHaveValue("Батон");
  await dialog.getByRole("button", { name: "Создать заново" }).click();

  await expect(dialog).toHaveCount(0);
  await expect(cardOf(helper.page, "Батон")).toBeVisible();
});

test("пустые экраны говорят, что делать дальше", async ({ browser }, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });

  await user.page.goto("/calendar");
  await expect(user.page.getByText("На этот день ничего нет")).toBeVisible();

  await user.page.goto("/tasks");
  await expect(user.page.getByText("Задач нет. Добавьте первую")).toBeVisible();
  await user.page.getByRole("button", { name: "Новая задача" }).last().click();
  await expect(user.page.getByRole("dialog", { name: "Новая задача" })).toBeVisible();

  const board = await kanbanBoard(user, "Дом");
  await user.page.goto(`/boards/${board.id}`);
  await expect(user.page.getByText("Перетащите карточку сюда").first()).toBeVisible();
});
