import { expect, test, type Page } from "@playwright/test";

import { signIn, type Member } from "./support";

const dialog = (page: Page, name: string) => page.getByRole("dialog", { name });

type Occurrence = { type: string; occurrence_start: string; is_recurring: boolean };

async function occurrences(member: Member, from: string, to: string): Promise<string[]> {
  const query = new URLSearchParams({ from, to });
  const { items } = await member.api<{ items: Occurrence[] }>(
    "GET",
    `calendar/items?${query.toString()}`,
  );
  return items.filter((item) => item.is_recurring).map((item) => item.occurrence_start);
}

function create(member: Member, body: Record<string, unknown>) {
  return member.api<{ id: string }>("POST", "events", {
    timezone: "Europe/Moscow",
    ...body,
  });
}

test("AC-08: a series of the first of the month shows in every month", async ({ browser }) => {
  const member = await signIn(browser, "Саша");
  await create(member, {
    title: "Счета",
    start_at: "2027-01-01T01:00:00+03:00",
    end_at: "2027-01-01T02:00:00+03:00",
    recurrence: { freq: "monthly" },
  });

  const year = await occurrences(member, "2026-12-31T21:00:00Z", "2027-12-31T21:00:00Z");

  expect(year).toHaveLength(12);
  await member.context.close();
});

test("AC-08: a series of the 31st skips the short months", async ({ browser }) => {
  const member = await signIn(browser, "Саша");
  await create(member, {
    title: "Отчёт",
    start_at: "2027-01-31T10:00:00+03:00",
    end_at: "2027-01-31T11:00:00+03:00",
    recurrence: { freq: "monthly" },
  });

  const year = await occurrences(member, "2026-12-31T21:00:00Z", "2027-12-31T21:00:00Z");

  expect(year.map((start) => start.slice(5, 7))).toEqual([
    "01",
    "03",
    "05",
    "07",
    "08",
    "10",
    "12",
  ]);
  await member.context.close();
});

test("AC-08: an endless series shows in a far period", async ({ browser }) => {
  const member = await signIn(browser, "Саша");
  await create(member, {
    title: "Йога",
    start_at: "2027-01-04T10:00:00+03:00",
    end_at: "2027-01-04T11:00:00+03:00",
    recurrence: { freq: "weekly" },
  });

  const month = await occurrences(member, "2090-03-01T00:00:00Z", "2090-04-01T00:00:00Z");

  expect(month.length).toBeGreaterThanOrEqual(4);
  await member.context.close();
});

test("a series made in the form repeats on the grid and opens its own date", async ({
  browser,
}) => {
  const member = await signIn(browser, "Саша");
  const { page } = member;
  await page.goto("/calendar?view=month&day=2030-06-14");

  await page.getByRole("button", { name: "Новое событие" }).click();
  const form = dialog(page, "Новое событие");
  await form.getByLabel("Название").fill("Планёрка");
  await form.getByLabel("Начало", { exact: true }).fill("2030-06-03");
  await form.getByLabel("Конец", { exact: true }).fill("2030-06-03");
  await form.getByLabel("Повторение").selectOption({ label: "Каждую неделю" });
  await form.getByLabel("Окончание серии").selectOption({ label: "N раз" });
  await form.getByLabel("Сколько раз").fill("3");
  await form.getByLabel("Напоминание").selectOption({ label: "За 15 минут" });
  await form.getByRole("button", { name: "Создать" }).click();
  await expect(form).toBeHidden();

  await page.goto("/calendar?view=day&day=2030-06-17");
  await page
    .getByRole("button", { name: /Планёрка/ })
    .first()
    .click();

  const view = dialog(page, "Планёрка");
  await expect(view.getByText("17 июня")).toBeVisible();
  await expect(view.getByText("Каждую неделю, 3 раза")).toBeVisible();
  await expect(view.getByLabel("Напоминание")).toHaveValue("15");
  await member.context.close();
});

test("AC-10: the worker delivers a reminder to the bell", async ({ browser }, testInfo) => {
  testInfo.setTimeout(150_000);
  test.skip(testInfo.project.name !== "desktop", "one size is enough for the worker");
  const member = await signIn(browser, "Саша");
  const start = new Date(Date.now() + 5_000);
  start.setMilliseconds(0);
  const end = new Date(start.getTime() + 60 * 60_000);
  await member.api("POST", "events", {
    title: "Созвон",
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    reminder_minutes: [0],
  });

  const { page } = member;
  await page.goto("/calendar");
  const bell = page.getByRole("button", { name: /Уведомления/ });
  await expect(bell).toContainText("1", { timeout: 60_000 });

  await bell.click();
  await expect(page.getByText("Скоро начнётся: Созвон")).toBeVisible();
  await member.context.close();
});
