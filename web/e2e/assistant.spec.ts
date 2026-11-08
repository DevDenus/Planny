import { expect, test, type Page } from "@playwright/test";

import { cardOf, signIn } from "./support";

/** The fake inference server of the stack answers with canned cards: see deploy/e2e. */
function tomorrow(): string {
  const day = new Date(Date.now() + 24 * 60 * 60 * 1000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(day);
}

const message = (page: Page) => page.getByLabel("Сообщение");

async function openAssistant(page: Page) {
  await page.getByRole("link", { name: "Ассистент" }).first().click();
  await expect(page).toHaveURL(/\/assistant/);
}

async function say(page: Page, text: string) {
  await message(page).fill(text);
  await page.getByRole("button", { name: "Отправить" }).click();
}

test("текст: задача из сообщения создаётся и остаётся в чатах", async ({ browser }, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  const { page } = user;
  await openAssistant(page);
  await say(page, "Купить молоко завтра");

  const card = page.getByRole("region", { name: "Задача" });
  await expect(card.getByLabel("Название")).toHaveValue("Купить молоко");
  await expect(card.getByLabel("Дедлайн")).toHaveValue(tomorrow());
  await expect(card.getByText("Молоко 3,2%")).toBeVisible();
  await card.getByRole("button", { name: "Создать задачу" }).click();

  await expect(page).toHaveURL(/\/boards\/[0-9a-f-]+/);
  await expect(cardOf(page, "Купить молоко")).toBeVisible();

  await openAssistant(page);
  if (testInfo.project.name === "phone")
    await page.getByRole("button", { name: "История" }).click();
  await expect(
    page.getByRole("link", { name: /Купить молоко/ }).getByText("Создано"),
  ).toBeVisible();
});

test("правка: ответ на сообщение меняет форму события", async ({ browser }, testInfo) => {
  const user = await signIn(browser, "Саша", { ...testInfo.project.use });
  const { page } = user;
  await openAssistant(page);
  await say(page, "Ужин завтра в семь");

  const card = page.getByRole("region", { name: "Событие" });
  await expect(card.getByLabel("Название")).toHaveValue("Ужин");
  await expect(card.getByLabel("Время начала")).toHaveValue("19:00");

  await say(page, "перенеси на восемь");
  await expect(card.getByLabel("Время начала")).toHaveValue("20:00");
  await card.getByRole("button", { name: "Создать событие" }).click();

  await expect(page).toHaveURL(new RegExp(`/calendar\\?day=${tomorrow()}`));
  await expect(page.getByRole("button", { name: /Ужин/ }).first()).toBeVisible();
});

// The browsers start with a fake microphone: see playwright.config.ts.
test("запись превращается в текст и сама не отправляется", async ({ browser }, testInfo) => {
  const user = await signIn(browser, "Саша", {
    ...testInfo.project.use,
    permissions: ["microphone"],
  });
  const { page } = user;
  await openAssistant(page);

  await page.getByRole("button", { name: "Записать голос" }).click();
  await expect(page.getByText(/Запись/)).toBeVisible();
  await page.waitForTimeout(1000);
  await page.getByRole("button", { name: "Готово" }).click();

  await expect(message(page)).toHaveValue("Купить молоко завтра");
  await expect(page.getByRole("region", { name: "Задача" })).toBeHidden();
});
