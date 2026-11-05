import { expect, test, type Locator, type Page } from "@playwright/test";

import { centre, signIn, type Member } from "./support";

/** The browsers of the tests live in Moscow, as the users do by default. */
function moscowDay(date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(date);
}

const TODAY = moscowDay();
const moment = (time: string) => new Date(`${TODAY}T${time}:00+03:00`).toISOString();

const dialog = (page: Page, name: string) => page.getByRole("dialog", { name });
const eventRow = (page: Page, title: string) =>
  page.getByRole("button", { name: new RegExp(title) }).first();
const dayPanel = (page: Page, day: string) =>
  page.getByRole("heading", { name: day }).locator("..");

let people = 0;

/** Users stay for the whole run and the form lists all of them, so a name has to tell them apart. */
function uniqueName(name: string): string {
  people += 1;
  return `${name} ${Date.now() % 100_000}-${people}`;
}

/**
 * The input of a checkbox is covered by its drawing, and the click lands on the label as usual.
 * A forced click doesn't wait, and a deadline stays disabled until the boards are known.
 */
async function toggle(checkbox: Locator) {
  await expect(checkbox).toBeEnabled();
  await checkbox.click({ force: true });
}

/** Returns once the counters are known: a change after this moment reaches the open tab. */
async function openCalendar({ page }: Member, path = "/calendar") {
  const synced = page.waitForResponse("**/api/v1/sync");
  await page.goto(path);
  await synced;
}

async function createInForm(page: Page, title: string, participant?: string) {
  await page.getByRole("button", { name: "Новое событие" }).click();
  const form = dialog(page, "Новое событие");
  await form.getByLabel("Название").fill(title);
  if (participant) await toggle(form.getByRole("checkbox", { name: participant }));
  await form.getByRole("button", { name: "Создать" }).click();
  await expect(form).toBeHidden();
}

async function openBell(page: Page) {
  await page.getByRole("button", { name: /Уведомления/ }).click();
  return dialog(page, "Уведомления");
}

test("AC-04: совместное событие, общие правки и удаление у всех", async ({ browser }) => {
  const guestName = uniqueName("Женя");
  const owner = await signIn(browser, "Саша");
  const guest = await signIn(browser, guestName);
  await openCalendar(owner);
  await openCalendar(guest);

  await createInForm(owner.page, "Ужин вдвоём", guestName);

  // AC-12: the other tab gets it by itself, 10 seconds at the very most.
  await expect(eventRow(guest.page, "Ужин вдвоём")).toBeVisible({ timeout: 10_000 });
  const guestBell = await openBell(guest.page);
  await guestBell.getByText("Новое совместное событие: Ужин вдвоём").click();

  const view = dialog(guest.page, "Ужин вдвоём");
  await view.getByRole("button", { name: "Изменить" }).click();
  const form = dialog(guest.page, "Изменить событие");
  await form.getByLabel("Название").fill("Поздний ужин");
  await form.getByRole("button", { name: "Сохранить" }).click();
  await expect(form).toBeHidden();

  await expect(eventRow(owner.page, "Поздний ужин")).toBeVisible({ timeout: 10_000 });
  const ownerBell = await openBell(owner.page);
  await expect(ownerBell.getByText("Изменилось событие: Поздний ужин")).toBeVisible();
  await owner.page.keyboard.press("Escape");
  await expect(ownerBell).toBeHidden();

  await eventRow(owner.page, "Поздний ужин").click();
  const ownerView = dialog(owner.page, "Поздний ужин");
  await ownerView.getByRole("button", { name: "Удалить" }).click();
  const confirm = dialog(owner.page, "Удалить событие?");
  await expect(confirm.getByText("Событие удалится у всех участников")).toBeVisible();
  await confirm.getByRole("button", { name: "Удалить" }).click();
  await expect(ownerView).toBeHidden();

  await expect(guest.page.getByRole("button", { name: /Поздний ужин/ })).toHaveCount(0, {
    timeout: 10_000,
  });
  await expect(owner.page.getByRole("button", { name: /Поздний ужин/ })).toHaveCount(0);
});

test("участник выходит из события, не затрагивая другого", async ({ browser }) => {
  const owner = await signIn(browser, "Саша");
  const guest = await signIn(browser, "Женя");
  await owner.api("POST", "events", {
    title: "Встреча",
    start_at: moment("15:00"),
    end_at: moment("16:00"),
    participant_ids: [guest.id],
  });
  await guest.page.goto("/calendar");

  await eventRow(guest.page, "Встреча").click();
  const view = dialog(guest.page, "Встреча");
  await view.getByRole("button", { name: "Выйти из события" }).click();
  await expect(view).toBeHidden();

  await expect(guest.page.getByRole("button", { name: /Встреча/ })).toBeHidden();
  await owner.page.goto("/calendar");
  await expect(eventRow(owner.page, "Встреча")).toBeVisible();
});

test("AC-05: занятость видна только как интервалы, без деталей", async ({ browser }) => {
  const busyName = uniqueName("Саша");
  const busy = await signIn(browser, busyName);
  const other = await signIn(browser, "Женя");
  await busy.api("POST", "events", {
    title: "Секретная встреча",
    start_at: moment("09:30"),
    end_at: moment("10:30"),
    location: "Секретное место",
  });
  await busy.api("POST", "events", {
    title: "Встреча вплотную",
    start_at: moment("10:30"),
    end_at: moment("11:00"),
  });
  await busy.api("POST", "events", {
    title: "День рождения",
    all_day: true,
    start_date: TODAY,
    end_date: TODAY,
  });
  await busy.api("POST", "tasks", { title: "Срок", due_date: TODAY });

  const answer = await other.api<{ items: { busy: object[] }[] }>(
    "GET",
    `availability?user_ids=${busy.id}&from=${moment("00:00")}&to=${moment("23:59")}`,
  );
  expect(answer.items[0]?.busy).toEqual([
    {
      start_at: moment("09:30").replace(".000Z", "Z"),
      end_at: moment("11:00").replace(".000Z", "Z"),
    },
  ]);

  await other.page.goto("/calendar");
  await other.page.getByRole("button", { name: "Новое событие" }).click();
  const form = dialog(other.page, "Новое событие");
  await toggle(form.getByRole("checkbox", { name: busyName }));
  await expect(
    form.getByText(`Пересечение по времени: ${busyName}`, { exact: false }),
  ).toBeVisible();

  // Saving is still allowed, and the title of the other event appears nowhere.
  await expect(form.getByText(/Секретная/)).toBeHidden();
  await form.getByLabel("Название").fill("Всё равно встретимся");
  await form.getByRole("button", { name: "Создать" }).click();
  await expect(form).toBeHidden();
});

test("при редактировании событие не пересекается само с собой", async ({ browser }) => {
  const owner = await signIn(browser, "Саша");
  await owner.api("POST", "events", {
    title: "Встреча",
    start_at: moment("15:00"),
    end_at: moment("16:00"),
  });
  await owner.page.goto("/calendar");

  await eventRow(owner.page, "Встреча").click();
  await dialog(owner.page, "Встреча").getByRole("button", { name: "Изменить" }).click();
  const form = dialog(owner.page, "Изменить событие");
  await expect(form.getByText("Занятость на этот день")).toBeVisible();
  await expect(form.getByText(/Пересечение по времени/)).toBeHidden();
});

test("AC-06: участники доски видят согласованный срок в календаре", async ({ browser }) => {
  const owner = await signIn(browser, "Саша");
  const helper = await signIn(browser, "Женя");
  const board = await owner.api<{ id: string }>("POST", "boards", { name: "Дом" });
  await owner.api("POST", `boards/${board.id}/members`, { user_id: helper.id, role: "editor" });
  await openCalendar(helper);

  const card = await owner.api<{ id: string; version: number }>("POST", "tasks", {
    board_id: board.id,
    title: "Купить продукты",
    due_date: TODAY,
  });

  await expect(eventRow(helper.page, "Купить продукты")).toBeVisible({ timeout: 10_000 });

  await owner.page.goto(`/boards/${board.id}`);
  await owner.page.getByRole("radio", { name: "Календарь" }).click();
  await expect(owner.page.getByText("Купить продукты").first()).toBeVisible();

  await toggle(helper.page.getByRole("checkbox", { name: "Выполнить: Купить продукты" }));
  await expect(helper.page.getByRole("checkbox", { name: /Вернуть в работу/ })).toBeVisible();
  await expect
    .poll(async () => {
      const task = await owner.api<{ completed_at: string | null }>("GET", `tasks/${card.id}`);
      return task.completed_at;
    })
    .not.toBeNull();
});

test("AC-09: событие на весь день стоит в тот же день в разных часовых поясах", async ({
  browser,
}) => {
  const tokyo = await signIn(browser, "Токио");
  const honolulu = await signIn(browser, "Гонолулу");
  await tokyo.api("PATCH", "me", { timezone: "Asia/Tokyo" });
  await honolulu.api("PATCH", "me", { timezone: "Pacific/Honolulu" });
  await tokyo.api("POST", "events", {
    title: "День рождения",
    all_day: true,
    start_date: "2027-03-10",
    end_date: "2027-03-10",
    participant_ids: [honolulu.id],
  });

  for (const { page } of [tokyo, honolulu]) {
    const birthday = (day: string) =>
      dayPanel(page, day).getByRole("button", { name: /День рождения/ });

    await page.goto("/calendar?day=2027-03-10");
    await expect(birthday("Ср, 10 марта")).toBeVisible();
    await page.goto("/calendar?day=2027-03-09");
    await expect(page.getByRole("heading", { name: "Вт, 9 марта" })).toBeVisible();
    await expect(birthday("Вт, 9 марта")).toBeHidden();
    await page.goto("/calendar?day=2027-03-11");
    await expect(page.getByRole("heading", { name: "Чт, 11 марта" })).toBeVisible();
    await expect(birthday("Чт, 11 марта")).toBeHidden();
  }
});

test("поиск находит событие и задачу и открывает их", async ({ browser, isMobile }) => {
  const owner = await signIn(browser, "Саша");
  await owner.api("POST", "events", {
    title: "Ужин с друзьями",
    start_at: moment("19:00"),
    end_at: moment("20:00"),
  });
  await owner.api("POST", "tasks", { title: "Ужин приготовить" });
  await owner.page.goto("/calendar");

  if (isMobile) await owner.page.getByRole("button", { name: "Поиск" }).click();
  await owner.page.getByRole("searchbox", { name: "Поиск" }).fill("ужин");
  const results = isMobile ? dialog(owner.page, "Поиск") : owner.page.getByRole("banner");
  await expect(results.getByRole("button", { name: /Ужин приготовить/ })).toBeVisible();
  await results.getByRole("button", { name: /Ужин с друзьями/ }).click();

  await expect(dialog(owner.page, "Ужин с друзьями")).toBeVisible();
});

test("задача связывается с событием с обеих сторон", async ({ browser }) => {
  const owner = await signIn(browser, "Саша");
  const task = await owner.api<{ id: string }>("POST", "tasks", { title: "Купить цветы" });
  await owner.api("POST", "events", {
    title: "Ужин",
    start_at: moment("19:00"),
    end_at: moment("20:00"),
  });

  await owner.page.goto(`/tasks?task=${task.id}`);
  const form = dialog(owner.page, "Задача");
  await form.getByLabel("Найти событие").fill("Ужин");
  await form.getByRole("button", { name: /Ужин/ }).click();
  await expect(form.getByRole("button", { name: "Убрать связь: Ужин" })).toBeVisible();

  await form.getByRole("button", { name: /Ужин/ }).first().click();
  const view = dialog(owner.page, "Ужин");
  await expect(view.getByText("Связанные задачи")).toBeVisible();
  await expect(view.getByRole("button", { name: "Купить цветы" })).toBeVisible();
});

test.describe("настольная сетка", () => {
  test.skip(({ isMobile }) => isMobile, "на телефоне компактный месяц");

  test("вид недели: клик по пустому часу открывает форму с этим временем", async ({ browser }) => {
    const owner = await signIn(browser, "Саша");
    await owner.page.goto("/calendar");
    await owner.page.getByRole("radio", { name: "Неделя" }).click();
    await expect(owner.page).toHaveURL(/view=week/);

    // The lanes of the days lie over the hours, so the click goes by coordinates, as a mouse does.
    const { x, y } = await centre(owner.page.locator('[data-time="14:00:00"]').last());
    await owner.page.mouse.click(x, y);

    const form = dialog(owner.page, "Новое событие");
    await expect(form.getByLabel("Время начала")).toHaveValue("14:00");
    await expect(form.getByLabel("Время конца")).toHaveValue("15:00");
  });

  test("категории и слой задач переключаются в левой панели", async ({ browser }) => {
    const owner = await signIn(browser, "Саша");
    const categories = await owner.api<{ items: { id: string; name: string }[] }>(
      "GET",
      "categories",
    );
    await owner.api("POST", "events", {
      title: "Рабочая встреча",
      start_at: moment("15:00"),
      end_at: moment("16:00"),
      category_id: categories.items.find((item) => item.name === "Работа")?.id,
    });
    await owner.api("POST", "tasks", { title: "Срок задачи", due_date: TODAY });
    await owner.page.goto("/calendar");
    await expect(eventRow(owner.page, "Рабочая встреча")).toBeVisible();

    const filters = owner.page.getByRole("navigation", { name: "Категории" });
    await filters.getByRole("switch", { name: "Работа" }).click();
    await expect(owner.page.getByRole("button", { name: /Рабочая встреча/ })).toBeHidden();

    await filters.getByRole("switch", { name: "Задачи" }).click();
    await expect(owner.page.getByRole("button", { name: /Срок задачи/ })).toBeHidden();

    await owner.page.reload();
    await expect(owner.page.getByRole("button", { name: /Рабочая встреча/ })).toBeHidden();
  });
});

test.describe("телефон", () => {
  test.skip(({ isMobile }) => !isMobile, "только на телефоне");

  test("компактный месяц с точками и список выбранного дня", async ({ browser }, testInfo) => {
    const owner = await signIn(browser, "Саша", { ...testInfo.project.use });
    const tomorrow = moscowDay(new Date(Date.now() + 24 * 60 * 60 * 1000));
    await owner.api("POST", "events", {
      title: "Завтрашнее дело",
      all_day: true,
      start_date: tomorrow,
      end_date: tomorrow,
    });
    await owner.page.goto("/calendar");

    await expect(owner.page.getByRole("radio", { name: "Неделя" })).toBeHidden();
    await expect(owner.page.getByRole("button", { name: /Завтрашнее дело/ })).toBeHidden();
    await owner.page.locator(`button[aria-pressed="true"]`).waitFor();
    await owner.page.goto(`/calendar?day=${tomorrow}`);
    await expect(eventRow(owner.page, "Завтрашнее дело")).toBeVisible();
  });
});
