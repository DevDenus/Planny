import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  expect,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const PASSWORD = "family-planner-2026";
const COMPOSE = [
  "compose",
  "--project-directory",
  `${ROOT}/deploy`,
  "-f",
  `${ROOT}/deploy/compose.yaml`,
  "-f",
  `${ROOT}/deploy/compose.e2e.yaml`,
];

let sequence = 0;

/** The way an operator makes an account: the app has no sign-up. */
function createAccount(login: string, name: string): string {
  const output = execFileSync(
    "docker",
    [...COMPOSE, "exec", "-T", "api", "planny", "users", "create", login, "--name", name],
    { encoding: "utf8" },
  );
  const password = /Одноразовый пароль: (\S+)/.exec(output)?.[1];
  if (!password) throw new Error(`no password in: ${output}`);
  return password;
}

export type Member = {
  id: string;
  context: BrowserContext;
  page: Page;
  api: <T = Record<string, never>>(method: string, path: string, body?: unknown) => Promise<T>;
};

export async function signIn(
  browser: Browser,
  name: string,
  options: Parameters<Browser["newContext"]>[0] = {},
): Promise<Member> {
  sequence += 1;
  const login = `e2e${Date.now() % 1_000_000}${sequence}`;
  const oneTime = createAccount(login, name);
  const context = await browser.newContext(options);
  const page = await context.newPage();

  await page.goto("/login");
  await page.getByLabel("Логин").fill(login);
  await page.getByLabel("Пароль", { exact: true }).fill(oneTime);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Новый пароль").fill(PASSWORD);
  await page.getByLabel("Повторите пароль").fill(PASSWORD);
  await page.getByRole("button", { name: "Сохранить пароль" }).click();
  await page.waitForURL("**/calendar");

  const api: Member["api"] = async <T>(method: string, path: string, body?: unknown) => {
    const cookies = await context.cookies();
    const csrf = cookies.find((cookie) => cookie.name.endsWith("planny_csrf"))?.value ?? "";
    const response = await context.request.fetch(`/bff/api/v1/${path}`, {
      method,
      headers: { "X-CSRF-Token": csrf },
      data: body,
    });
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
    return (response.status() === 204 ? {} : await response.json()) as T;
  };
  const me = await api<{ id: string }>("GET", "me");
  return { id: me.id, context, page, api };
}

export type Column = { id: string; name: string };
export type Card = { id: string; title: string };

export async function kanbanBoard(owner: Member, name: string) {
  const board = await owner.api<{ id: string }>("POST", "boards", { name, default_view: "kanban" });
  const { items } = await owner.api<{ items: Column[] }>("GET", `boards/${board.id}/columns`);
  const [todo, done] = items;
  if (!todo || !done) throw new Error("a new board has two columns");
  return { id: board.id, todo, done };
}

export function addCard(owner: Member, boardId: string, columnId: string, title: string) {
  return owner.api<Card>("POST", "tasks", { board_id: boardId, column_id: columnId, title });
}

export const columnOf = (page: Page, name: string) => page.getByRole("region", { name });

export const cardOf = (page: Page, title: string) => page.locator(`[data-card-title="${title}"]`);

export function titlesIn(page: Page, column: string) {
  return columnOf(page, column)
    .locator("[data-card-title]")
    .evaluateAll((cards) => cards.map((card) => card.getAttribute("data-card-title")));
}

export async function centre(selector: Locator) {
  await selector.scrollIntoViewIfNeeded();
  const box = await selector.boundingBox();
  if (!box) throw new Error("the element has no box");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
}
