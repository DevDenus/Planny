import { expect, test, type CDPSession } from "@playwright/test";

import { addCard, cardOf, centre, columnOf, kanbanBoard, signIn, titlesIn } from "./support";

test.describe("перетаскивание мышью", () => {
  test.skip(({ isMobile }) => isMobile, "на телефоне нет мыши");

  test("карточка переносится между колонками, остаётся после перезагрузки и видна другому пользователю", async ({
    browser,
  }) => {
    const owner = await signIn(browser, "Саша");
    const helper = await signIn(browser, "Женя");
    const board = await kanbanBoard(owner, "Дом");
    await owner.api("POST", `boards/${board.id}/members`, { user_id: helper.id, role: "editor" });
    const moved = await addCard(owner, board.id, board.todo.id, "Хлеб");
    await addCard(owner, board.id, board.done.id, "Молоко");

    await helper.page.goto(`/boards/${board.id}`);
    await expect(cardOf(helper.page, "Хлеб")).toBeVisible();
    await owner.page.goto(`/boards/${board.id}`);
    await expect(cardOf(owner.page, "Хлеб")).toBeVisible();

    const from = await centre(cardOf(owner.page, "Хлеб"));
    const to = await centre(cardOf(owner.page, "Молоко"));
    await owner.page.mouse.move(from.x, from.y);
    await owner.page.mouse.down();
    await owner.page.mouse.move(from.x + 12, from.y + 12, { steps: 3 });
    await owner.page.mouse.move(to.x, to.box.y + to.box.height - 2, { steps: 12 });
    await expect(owner.page.locator("[data-drop-line]")).toBeVisible();
    await owner.page.mouse.up();

    await expect.poll(() => titlesIn(owner.page, "Готово")).toEqual(["Молоко", "Хлеб"]);
    await owner.page.reload();
    await expect.poll(() => titlesIn(owner.page, "Готово")).toEqual(["Молоко", "Хлеб"]);
    await expect(cardOf(owner.page, "Хлеб").getByLabel("Выполнено")).toBeVisible();

    // AC-13: the other user sees it by the next poll, 10 seconds at the very most.
    await expect
      .poll(() => titlesIn(helper.page, "Готово"), { timeout: 10_000 })
      .toEqual(["Молоко", "Хлеб"]);
    const task = await owner.api<{ id: string }>("GET", `tasks/${moved.id}`);
    expect(task.id).toBe(moved.id);
  });

  test("внутри колонки карточка меняет порядок", async ({ browser }) => {
    const owner = await signIn(browser, "Саша");
    const board = await kanbanBoard(owner, "Дом");
    for (const title of ["a", "b", "c"]) await addCard(owner, board.id, board.todo.id, title);
    await owner.page.goto(`/boards/${board.id}`);

    const from = await centre(cardOf(owner.page, "c"));
    const to = await centre(cardOf(owner.page, "a"));
    await owner.page.mouse.move(from.x, from.y);
    await owner.page.mouse.down();
    await owner.page.mouse.move(from.x, from.y - 12, { steps: 3 });
    await owner.page.mouse.move(to.x, to.box.y + 2, { steps: 12 });
    await owner.page.mouse.up();

    await expect.poll(() => titlesIn(owner.page, "К выполнению")).toEqual(["c", "a", "b"]);
  });

  test("Esc и отпускание вне колонки возвращают карточку на место", async ({ browser }) => {
    const owner = await signIn(browser, "Саша");
    const board = await kanbanBoard(owner, "Дом");
    await addCard(owner, board.id, board.todo.id, "a");
    await owner.page.goto(`/boards/${board.id}`);

    const from = await centre(cardOf(owner.page, "a"));
    const target = await centre(columnOf(owner.page, "Готово"));
    await owner.page.mouse.move(from.x, from.y);
    await owner.page.mouse.down();
    await owner.page.mouse.move(target.x, target.y, { steps: 10 });
    await owner.page.keyboard.press("Escape");
    await owner.page.mouse.up();
    await expect.poll(() => titlesIn(owner.page, "К выполнению")).toEqual(["a"]);

    await owner.page.mouse.move(from.x, from.y);
    await owner.page.mouse.down();
    await owner.page.mouse.move(from.x + 20, 10, { steps: 10 });
    await owner.page.mouse.up();
    await expect.poll(() => titlesIn(owner.page, "К выполнению")).toEqual(["a"]);
    await expect(owner.page.locator("[data-drop-line]")).toHaveCount(0);
  });

  test("колонка перетаскивается за заголовок", async ({ browser }) => {
    const owner = await signIn(browser, "Саша");
    const board = await kanbanBoard(owner, "Дом");
    await owner.page.goto(`/boards/${board.id}`);

    const from = await centre(columnOf(owner.page, "Готово").getByRole("heading"));
    const to = await centre(columnOf(owner.page, "К выполнению"));
    await owner.page.mouse.move(from.x, from.y);
    await owner.page.mouse.down();
    await owner.page.mouse.move(from.x - 12, from.y, { steps: 3 });
    await owner.page.mouse.move(to.box.x + 4, to.y, { steps: 12 });
    await owner.page.mouse.up();

    const headings = owner.page.getByRole("region").getByRole("heading");
    await expect(headings).toHaveText(["Готово", "К выполнению"]);
  });
});

test("клавиатура: пробел берёт, стрелки двигают, пробел отпускает, Esc отменяет", async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name === "phone", "у телефона нет клавиатуры");
  const owner = await signIn(browser, "Саша");
  const board = await kanbanBoard(owner, "Дом");
  await addCard(owner, board.id, board.todo.id, "a");
  await addCard(owner, board.id, board.todo.id, "b");
  await owner.page.goto(`/boards/${board.id}`);
  const { keyboard } = owner.page;

  await cardOf(owner.page, "b").getByRole("button").first().focus();
  await keyboard.press("Space");
  await keyboard.press("ArrowUp");
  await keyboard.press("Space");
  await expect.poll(() => titlesIn(owner.page, "К выполнению")).toEqual(["b", "a"]);
  await expect(cardOf(owner.page, "b").getByRole("button").first()).toBeFocused();

  await keyboard.press("Space");
  await keyboard.press("ArrowRight");
  await keyboard.press("Space");
  await expect.poll(() => titlesIn(owner.page, "Готово")).toEqual(["b"]);
  await expect(cardOf(owner.page, "b").getByRole("button").first()).toBeFocused();

  await keyboard.press("Space");
  await keyboard.press("ArrowLeft");
  await keyboard.press("Escape");
  await expect(owner.page.locator("[data-drop-line]")).toHaveCount(0);
  await owner.page.reload();
  await expect.poll(() => titlesIn(owner.page, "Готово")).toEqual(["b"]);
});

test("вид «Список»: строка перетаскивается между колонками и остаётся на месте", async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name === "phone", "мышь есть только на компьютере");
  const owner = await signIn(browser, "Саша");
  const board = await owner.api<{ id: string }>("POST", "boards", { name: "Покупки" });
  const { items } = await owner.api<{ items: { id: string }[] }>(
    "GET",
    `boards/${board.id}/columns`,
  );
  const [todo] = items;
  if (!todo) throw new Error("a new board has columns");
  for (const title of ["a", "b"]) await addCard(owner, board.id, todo.id, title);
  await owner.page.goto(`/boards/${board.id}`);

  const from = await centre(cardOf(owner.page, "b"));
  const to = await centre(cardOf(owner.page, "a"));
  await owner.page.mouse.move(from.x, from.y);
  await owner.page.mouse.down();
  await owner.page.mouse.move(from.x, from.y - 10, { steps: 3 });
  await owner.page.mouse.move(to.x, to.box.y + 2, { steps: 10 });
  await owner.page.mouse.up();

  const order = () =>
    owner.page
      .locator("[data-card-title]")
      .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-card-title")));
  await expect.poll(order).toEqual(["b", "a"]);
  await owner.page.reload();
  await expect.poll(order).toEqual(["b", "a"]);
});

test("форма задачи переносит карточку на другую доску, сбрасывая метки", async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name === "phone", "сценарий формы один на оба размера");
  const owner = await signIn(browser, "Саша");
  const home = await kanbanBoard(owner, "Дом");
  const work = await kanbanBoard(owner, "Работа");
  const label = await owner.api<{ id: string }>("POST", `boards/${home.id}/labels`, {
    name: "Идея",
    color: "blue",
  });
  const card = await owner.api<{ id: string }>("POST", "tasks", {
    board_id: home.id,
    title: "Хлеб",
    label_ids: [label.id],
  });

  await owner.page.goto(`/boards/${home.id}?task=${card.id}`);
  const dialog = owner.page.getByRole("dialog");
  await dialog.getByLabel("Название").waitFor();
  await dialog.getByLabel("Доска").selectOption({ label: "Работа" });
  await dialog.getByRole("button", { name: "Сохранить" }).click();
  await expect(dialog).toHaveCount(0);

  await owner.page.goto(`/boards/${work.id}`);
  await expect(cardOf(owner.page, "Хлеб")).toBeVisible();
  const moved = await owner.api<{ labels: unknown[]; board_name: string }>(
    "GET",
    `tasks/${card.id}`,
  );
  expect(moved.board_name).toBe("Работа");
  expect(moved.labels).toEqual([]);

  await cardOf(owner.page, "Хлеб").getByRole("button").first().click();
  await owner.page.getByRole("radio", { name: "История" }).click();
  await expect(owner.page.getByText("Перенос: Дом, К выполнению → Работа")).toBeVisible();
  await expect(owner.page.getByText("Убрана метка: Идея")).toBeVisible();
});

test.describe("касание", () => {
  test.skip(({ isMobile }) => !isMobile, "только телефон");

  async function touch(
    session: CDPSession,
    type: "touchStart" | "touchMove" | "touchEnd",
    x = 0,
    y = 0,
  ) {
    await session.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: type === "touchEnd" ? [] : [{ x, y }],
    });
  }

  test("долгое нажатие переносит карточку в соседнюю колонку", async ({ browser }, testInfo) => {
    const { hasTouch, isMobile, viewport, userAgent, deviceScaleFactor } = testInfo.project.use;
    const owner = await signIn(browser, "Саша", {
      hasTouch,
      isMobile,
      viewport,
      userAgent,
      deviceScaleFactor,
    });
    const board = await kanbanBoard(owner, "Дом");
    await addCard(owner, board.id, board.todo.id, "Хлеб");
    await addCard(owner, board.id, board.done.id, "Молоко");
    await owner.page.goto(`/boards/${board.id}`);
    await expect(cardOf(owner.page, "Хлеб")).toBeVisible();

    const session = await owner.context.newCDPSession(owner.page);
    const from = await centre(cardOf(owner.page, "Хлеб"));
    const width = owner.page.viewportSize()?.width ?? 400;

    await touch(session, "touchStart", from.x, from.y);
    await owner.page.waitForTimeout(400);
    for (let step = 1; step <= 10; step += 1) {
      await touch(session, "touchMove", from.x + ((width - 8 - from.x) * step) / 10, from.y);
    }
    // The pointer rests at the edge, and the board scrolls by itself to the next column.
    await expect
      .poll(async () => {
        await touch(session, "touchMove", width - 8, from.y + 1);
        return owner.page.locator("[data-drop-line]").count();
      })
      .toBeGreaterThan(0);
    await expect(columnOf(owner.page, "Готово").locator("[data-drop-line]")).toHaveCount(1, {
      timeout: 15_000,
    });
    await touch(session, "touchEnd");

    await expect.poll(() => titlesIn(owner.page, "Готово")).toContain("Хлеб");
    await owner.page.reload();
    await expect.poll(() => titlesIn(owner.page, "Готово")).toContain("Хлеб");
  });

  test("короткое движение пальцем прокручивает доску, а не тащит карточку", async ({
    browser,
  }, testInfo) => {
    const { hasTouch, isMobile, viewport, userAgent, deviceScaleFactor } = testInfo.project.use;
    const owner = await signIn(browser, "Саша", {
      hasTouch,
      isMobile,
      viewport,
      userAgent,
      deviceScaleFactor,
    });
    const board = await kanbanBoard(owner, "Дом");
    await addCard(owner, board.id, board.todo.id, "Хлеб");
    await owner.page.goto(`/boards/${board.id}`);
    await expect(cardOf(owner.page, "Хлеб")).toBeVisible();

    const session = await owner.context.newCDPSession(owner.page);
    const from = await centre(cardOf(owner.page, "Хлеб"));
    await touch(session, "touchStart", from.x, from.y);
    for (let step = 1; step <= 8; step += 1) {
      await touch(session, "touchMove", from.x - step * 30, from.y);
    }
    await touch(session, "touchEnd");

    await expect(owner.page.locator("[data-drop-line]")).toHaveCount(0);
    await expect.poll(() => titlesIn(owner.page, "К выполнению")).toEqual(["Хлеб"]);
  });

  test("на телефоне работает меню «Переместить в…»", async ({ browser }, testInfo) => {
    const { hasTouch, isMobile, viewport, userAgent, deviceScaleFactor } = testInfo.project.use;
    const owner = await signIn(browser, "Саша", {
      hasTouch,
      isMobile,
      viewport,
      userAgent,
      deviceScaleFactor,
    });
    const board = await kanbanBoard(owner, "Дом");
    await addCard(owner, board.id, board.todo.id, "Хлеб");
    await owner.page.goto(`/boards/${board.id}`);

    await owner.page.getByRole("button", { name: "Меню карточки: Хлеб" }).tap();
    await owner.page.getByRole("menuitem", { name: "Переместить в…" }).tap();
    await owner.page.getByLabel("Колонка").selectOption({ label: "Готово" });
    await owner.page.getByRole("button", { name: "Переместить", exact: true }).tap();

    await expect.poll(() => titlesIn(owner.page, "Готово")).toEqual(["Хлеб"]);
  });
});
