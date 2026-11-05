import { expect, test } from "@playwright/test";

import { addCard, columnOf, kanbanBoard, signIn } from "./support";

test("AC-15: колонку с карточками нельзя удалить без переноса, а последнюю нельзя совсем", async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name === "phone", "меню колонки одно на оба размера");
  const owner = await signIn(browser, "Саша");
  const board = await kanbanBoard(owner, "Дом");
  await addCard(owner, board.id, board.todo.id, "Хлеб");
  await owner.api("POST", `boards/${board.id}/columns`, { name: "В работе" });
  await owner.page.goto(`/boards/${board.id}`);

  const deleteItem = async (name: string) => {
    await owner.page.getByRole("button", { name: `Меню колонки: ${name}` }).click();
    return owner.page.getByRole("menuitem", { name: "Удалить" });
  };

  await (await deleteItem("К выполнению")).click();
  const dialog = owner.page.getByRole("dialog");
  await expect(dialog.getByLabel(/Куда перенести/)).toBeVisible();
  await dialog.getByLabel(/Куда перенести/).selectOption({ label: "В работе" });
  await dialog.getByRole("button", { name: "Удалить" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(columnOf(owner.page, "В работе").getByText("Хлеб")).toBeVisible();

  await expect(await deleteItem("Готово")).toBeDisabled();
});

test("AC-16, AC-17: комментарий, история и доступ читателя", async ({ browser }, testInfo) => {
  const owner = await signIn(browser, "Саша", { ...testInfo.project.use });
  const editor = await signIn(browser, "Женя", { ...testInfo.project.use });
  const viewer = await signIn(browser, "Боря", { ...testInfo.project.use });
  const board = await kanbanBoard(owner, "Дом");
  await owner.api("POST", `boards/${board.id}/members`, { user_id: editor.id, role: "editor" });
  await owner.api("POST", `boards/${board.id}/members`, { user_id: viewer.id, role: "viewer" });
  const card = await owner.api<{ id: string; version: number }>("POST", "tasks", {
    board_id: board.id,
    column_id: board.todo.id,
    title: "Хлеб",
    assignee_ids: [owner.id],
  });
  const column = await owner.api<{ id: string }>("POST", `boards/${board.id}/columns`, {
    name: "В работе",
  });
  await owner.api("POST", `tasks/${card.id}/move`, { column_id: column.id });
  await owner.api("PATCH", `boards/${board.id}/columns/${column.id}`, { name: "Делаем" });

  await editor.page.goto(`/boards/${board.id}?task=${card.id}`);
  await editor.page.getByLabel("Новый комментарий").fill("Купить свежий");
  await editor.page.getByRole("button", { name: "Отправить" }).click();
  await expect(editor.page.getByText("Купить свежий")).toBeVisible();

  await owner.page.goto("/calendar");
  await owner.page.getByRole("button", { name: /Уведомления/ }).click();
  await expect(
    owner.page.getByRole("dialog", { name: "Уведомления" }).getByText("Хлеб"),
  ).toBeVisible();

  await viewer.page.goto(`/boards/${board.id}?task=${card.id}`);
  const dialog = viewer.page.getByRole("dialog", { name: "Задача", exact: true });
  await expect(dialog.getByText("Доска доступна только для чтения")).toBeVisible();
  await expect(dialog.getByLabel("Название")).toBeDisabled();
  await expect(dialog.getByText("Купить свежий")).toBeVisible();
  await expect(dialog.getByLabel("Новый комментарий")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Сохранить" })).toHaveCount(0);

  await dialog.getByRole("radio", { name: "История" }).click();
  await expect(dialog.getByText(/Саша/).first()).toBeVisible();
  await expect(dialog.getByText("Перенос: К выполнению → В работе")).toBeVisible();
});
