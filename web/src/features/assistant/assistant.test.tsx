import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantChat, AssistantMessage } from "../../api/client";
import {
  API,
  USER,
  apiError,
  bodyOf,
  json,
  makeBoard,
  makeColumn,
  makeEvent,
  makeOccurrence,
  makeTask,
  path,
  renderApp,
  requestsTo,
  stubApp,
  type Stub,
} from "../tasks/testing";

const ASSISTANT = `${API}/assistant`;
const CHATS = `${ASSISTANT}/chats`;
const CHAT_ID = "11111111-1111-4111-8111-111111111111";

beforeEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "planny_csrf=; max-age=0";
});

function message(role: "user" | "assistant", text: string, id: string): AssistantMessage {
  return { id, role, text, warnings: [], created_at: "2026-11-06T10:00:00Z" };
}

function makeChat(overrides: Partial<AssistantChat> = {}): AssistantChat {
  return {
    id: CHAT_ID,
    title: "Купить молоко",
    kind: "task",
    state: "draft",
    updated_at: new Date().toISOString(),
    card: null,
    messages: [message("user", "Купить молоко", "m1"), message("assistant", "Готово", "m2")],
    ...overrides,
  };
}

type Setup = {
  status?: { enabled: boolean; voice: boolean };
  chats?: AssistantChat[];
  /** The answer to the first message of a new chat. */
  created?: AssistantChat;
  createError?: () => Response;
  /** The answer to a message in an existing chat. */
  sent?: () => Response;
  onTranscribe?: Stub;
};

/** The assistant routes on top of the app stub. */
function assistantRoutes({
  status = { enabled: true, voice: true },
  chats = [],
  created,
  createError,
  sent,
  onTranscribe,
}: Setup): Stub {
  return (request) => {
    const pathname = path(request);
    if (!pathname.startsWith(ASSISTANT)) return undefined;
    if (pathname === `${ASSISTANT}/status`) return json(200, status);
    if (pathname === `${ASSISTANT}/transcribe`) return onTranscribe?.(request);
    if (pathname === CHATS) {
      if (request.method === "POST") {
        if (!created) return createError?.();
        chats.push(created);
        return json(201, created);
      }
      return json(200, { items: chats });
    }
    const [id, child] = pathname.slice(CHATS.length + 1).split("/");
    const chat = chats.find((item) => item.id === id);
    if (!chat) return apiError(404, "not_found", "Не найдено");
    if (child === "messages") return sent!();
    if (request.method === "DELETE") return new Response(null, { status: 204 });
    return json(200, chat);
  };
}

const personal = makeBoard({ id: "b-personal", name: "Личная", is_default: true });
const column = makeColumn({ id: "c-todo", name: "К выполнению" });

function setup(options: Setup, route: string, extra: Parameters<typeof stubApp>[0] = {}) {
  const routes = assistantRoutes(options);
  const calls = stubApp({
    boards: [personal],
    columns: [column],
    ...extra,
    onRequest: (request) => routes(request) ?? extra.onRequest?.(request),
  });
  return { calls, user: userEvent.setup(), ...renderApp(route) };
}

const taskCard = {
  kind: "task" as const,
  title: "Купить молоко",
  board_id: personal.id,
  priority: 2,
  checklist: ["Молоко", "Хлеб"],
  due_date: "2026-11-09",
};

const composer = () => screen.getByRole("textbox", { name: "Сообщение" });

describe("navigation", () => {
  it("shows the section when the assistant is enabled", async () => {
    setup({ status: { enabled: true, voice: false } }, "/tasks");
    expect((await screen.findAllByRole("link", { name: "Ассистент" })).length).toBeGreaterThan(0);
  });

  it("hides the section when it is disabled", async () => {
    const { calls } = setup({ status: { enabled: false, voice: false } }, "/tasks");
    await waitFor(() => expect(requestsTo(calls, "GET", `${ASSISTANT}/status`)).toHaveLength(1));
    expect(screen.queryByRole("link", { name: "Ассистент" })).not.toBeInTheDocument();
  });
});

describe("a new chat", () => {
  it("fills the task form, creates the task with the chat id and opens the board", async () => {
    const created = makeChat({ card: taskCard });
    const { calls, user } = setup({ created }, "/assistant", {
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${API}/tasks`
          ? json(201, makeTask({ id: CHAT_ID, board_id: personal.id }))
          : undefined,
    });

    await user.type(
      await screen.findByRole("textbox", { name: "Сообщение" }),
      "Купить молоко{Enter}",
    );

    expect(await screen.findByDisplayValue("Купить молоко")).toBeInTheDocument();
    expect(requestsTo(calls, "POST", CHATS)).toHaveLength(1);
    expect(await bodyOf(requestsTo(calls, "POST", CHATS)[0]!)).toEqual({ text: "Купить молоко" });
    // The chat is open under its own address now.
    expect(await screen.findByRole("link", { name: /Купить молоко/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByLabelText("Дедлайн")).toHaveValue("2026-11-09");
    expect(screen.getByLabelText("Доска")).toHaveValue(personal.id);
    expect(screen.getByText("Молоко")).toBeInTheDocument();
    expect(screen.getByText("Хлеб")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Создать задачу" }));

    await waitFor(() => expect(requestsTo(calls, "POST", `${API}/tasks`)).toHaveLength(1));
    const body = await bodyOf(requestsTo(calls, "POST", `${API}/tasks`)[0]!);
    expect(body).toMatchObject({
      id: CHAT_ID,
      title: "Купить молоко",
      board_id: personal.id,
      due_date: "2026-11-09",
      checklist: ["Молоко", "Хлеб"],
    });
    expect(await screen.findByRole("heading", { name: "Личная" })).toBeInTheDocument();
    expect(screen.getByText("Задача создана")).toBeInTheDocument();
  });

  it("creates the event with the chat id and opens its day in the calendar", async () => {
    const created = makeChat({
      kind: "event",
      title: "Ужин",
      card: {
        kind: "event",
        title: "Ужин",
        all_day: false,
        timezone: "Europe/Moscow",
        start_at: "2026-11-06T16:00:00Z",
        end_at: "2026-11-06T17:00:00Z",
        participant_ids: [],
      },
    });
    const { calls, user } = setup({ created }, "/assistant", {
      calendarItems: [makeOccurrence({ title: "Ужин вдвоём" })],
      onRequest: (request) =>
        request.method === "POST" && path(request) === `${API}/events`
          ? json(201, makeEvent({ id: CHAT_ID }))
          : undefined,
    });

    await user.type(await screen.findByRole("textbox", { name: "Сообщение" }), "Ужин{Enter}");
    expect(await screen.findByLabelText("Время начала")).toHaveValue("19:00");

    await user.click(screen.getByRole("button", { name: "Создать событие" }));

    await waitFor(() => expect(requestsTo(calls, "POST", `${API}/events`)).toHaveLength(1));
    const body = await bodyOf(requestsTo(calls, "POST", `${API}/events`)[0]!);
    expect(body).toMatchObject({
      id: CHAT_ID,
      title: "Ужин",
      start_at: "2026-11-06T16:00:00Z",
      participant_ids: [USER.id],
    });
    expect((await screen.findAllByText("Ужин вдвоём")).length).toBeGreaterThan(0);
    expect(screen.getByText("Событие создано")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Создать событие" })).not.toBeInTheDocument();
  });

  it("puts the text back and says why when the assistant is unavailable", async () => {
    const { user } = setup(
      { createError: () => apiError(503, "assistant_unavailable", "Недоступно") },
      "/assistant",
    );
    await user.type(await screen.findByRole("textbox", { name: "Сообщение" }), "Привет");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("Ассистент сейчас недоступен")).toBeInTheDocument();
    expect(composer()).toHaveValue("Привет");
    expect(composer()).toBeEnabled();
  });
});

describe("an open draft", () => {
  it("sends the hand edits of the form with the next message", async () => {
    const chat = makeChat({ card: taskCard });
    const answer = makeChat({
      card: { ...taskCard, title: "Купить кефир" },
      messages: [...chat.messages, message("user", "ещё", "m3"), message("assistant", "ок", "m4")],
    });
    const { calls, user } = setup(
      { chats: [chat], sent: () => json(200, answer) },
      `/assistant/${CHAT_ID}`,
    );

    const title = await screen.findByLabelText("Название");
    await user.clear(title);
    await user.type(title, "Купить сыр");
    await user.type(composer(), "ещё{Enter}");

    await waitFor(() =>
      expect(requestsTo(calls, "POST", `${CHATS}/${CHAT_ID}/messages`)).toHaveLength(1),
    );
    const body = await bodyOf(requestsTo(calls, "POST", `${CHATS}/${CHAT_ID}/messages`)[0]!);
    expect(body).toMatchObject({
      text: "ещё",
      card: {
        kind: "task",
        title: "Купить сыр",
        board_id: personal.id,
        checklist: ["Молоко", "Хлеб"],
      },
    });
    // The new proposal replaces the form.
    expect(await screen.findByDisplayValue("Купить кефир")).toBeInTheDocument();
  });
});

describe("a created card", () => {
  it("shows the proposed change and saves it with the version", async () => {
    const task = makeTask({
      id: CHAT_ID,
      board_id: personal.id,
      column_id: column.id,
      title: "Старое название",
      priority: 3,
      version: 4,
    });
    const chat = makeChat({ state: "created", card: { ...taskCard, title: "Новое название" } });
    const { calls, user } = setup({ chats: [chat] }, `/assistant/${CHAT_ID}`, {
      tasks: [task],
      onRequest: (request) =>
        request.method === "PATCH" && path(request) === `${API}/tasks/${CHAT_ID}`
          ? json(200, { ...task, title: "Новое название", version: 5 })
          : undefined,
    });

    expect(await screen.findByDisplayValue("Новое название")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сохранить изменения" }));

    await waitFor(() =>
      expect(requestsTo(calls, "PATCH", `${API}/tasks/${CHAT_ID}`)).toHaveLength(1),
    );
    expect(await bodyOf(requestsTo(calls, "PATCH", `${API}/tasks/${CHAT_ID}`)[0]!)).toMatchObject({
      title: "Новое название",
      priority: 2,
      version: 4,
    });
    expect(requestsTo(calls, "POST", `${API}/tasks`)).toHaveLength(0);
    expect(await screen.findByRole("heading", { name: "Личная" })).toBeInTheDocument();
  });

  it("edits the whole event through the update", async () => {
    const event = makeEvent({ id: CHAT_ID, title: "Ужин", version: 2 });
    const chat = makeChat({
      kind: "event",
      state: "created",
      card: {
        kind: "event",
        title: "Поздний ужин",
        all_day: false,
        timezone: "Europe/Moscow",
        start_at: event.start_at,
        end_at: event.end_at,
      },
    });
    const { calls, user } = setup({ chats: [chat] }, `/assistant/${CHAT_ID}`, {
      events: [event],
      onRequest: (request) =>
        request.method === "PATCH" ? json(200, { ...event, title: "Поздний ужин" }) : undefined,
    });

    expect(await screen.findByDisplayValue("Поздний ужин")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сохранить изменения" }));

    await waitFor(() =>
      expect(requestsTo(calls, "PATCH", `${API}/events/${CHAT_ID}`)).toHaveLength(1),
    );
    expect(await bodyOf(requestsTo(calls, "PATCH", `${API}/events/${CHAT_ID}`)[0]!)).toEqual({
      title: "Поздний ужин",
      version: 2,
    });
  });
});

describe("a deleted card", () => {
  it("says so and closes the composer", async () => {
    const chat = makeChat({ state: "deleted", card: taskCard });
    setup({ chats: [chat] }, `/assistant/${CHAT_ID}`);

    expect((await screen.findAllByText("Карточка удалена")).length).toBeGreaterThan(0);
    expect(composer()).toBeDisabled();
    expect(screen.queryByLabelText("Название")).not.toBeInTheDocument();
  });
});

describe("voice input", () => {
  it("has no microphone button without voice", async () => {
    setup({ status: { enabled: true, voice: false } }, "/assistant");
    await screen.findByRole("textbox", { name: "Сообщение" });
    expect(screen.queryByRole("button", { name: "Записать голос" })).not.toBeInTheDocument();
  });

  it("records, sends the audio with its type and puts the text in the field without sending", async () => {
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop: stopTrack }] }));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    class FakeRecorder {
      static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
      state = "inactive";
      mimeType: string;
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      constructor(_stream: unknown, options?: { mimeType?: string }) {
        this.mimeType = options?.mimeType ?? "";
      }
      start() {
        this.state = "recording";
      }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["звук"], { type: this.mimeType }) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", FakeRecorder);

    const { calls, user } = setup(
      { onTranscribe: () => json(200, { text: "купить хлеб" }) },
      "/assistant",
    );
    await user.type(await screen.findByRole("textbox", { name: "Сообщение" }), "Сегодня");
    await user.click(screen.getByRole("button", { name: "Записать голос" }));
    expect(await screen.findByText(/Запись 0:0/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Готово" }));

    await waitFor(() => expect(composer()).toHaveValue("Сегодня купить хлеб"));
    const [request] = requestsTo(calls, "POST", `${ASSISTANT}/transcribe`);
    expect(request!.headers.get("Content-Type")).toBe("audio/webm;codecs=opus");
    expect((await request!.clone().arrayBuffer()).byteLength).toBeGreaterThan(0);
    expect(stopTrack).toHaveBeenCalled();
    await waitFor(() => expect(composer()).toHaveFocus());
    expect(requestsTo(calls, "POST", CHATS)).toHaveLength(0);
  });

  it("says when the microphone is not available", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => Promise.reject(new Error("denied")) },
    });
    const { user } = setup({}, "/assistant");
    await user.click(await screen.findByRole("button", { name: "Записать голос" }));
    expect(await screen.findByText("Нет доступа к микрофону")).toBeInTheDocument();
  });
});

describe("on a phone", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  });

  it("opens the history over the new chat", async () => {
    const chat = makeChat({ title: "Старый разговор" });
    const { user } = setup({ chats: [chat] }, "/assistant");

    await screen.findByRole("textbox", { name: "Сообщение" });
    expect(screen.queryByText("Старый разговор")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "История" }));
    expect(await screen.findByText("Старый разговор")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Сообщение" })).not.toBeInTheDocument();
  });

  it("shows an open chat with a way back", async () => {
    const chat = makeChat();
    const { user } = setup({ chats: [chat] }, `/assistant/${CHAT_ID}`);

    expect(await screen.findByText("Готово")).toBeInTheDocument();
    await user.click(within(screen.getByRole("main")).getByRole("link", { name: /Ассистент/ }));
    await waitFor(() => expect(screen.queryByText("Готово")).not.toBeInTheDocument());
    expect(composer()).toHaveValue("");
  });
});
