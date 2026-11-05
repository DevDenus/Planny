import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UserAvailability, UserSummary } from "../../api/client";
import { API, requestsTo, searchOf, stubApp, USER_SUMMARY } from "../tasks/testing";
import { BusyHint, overlaps, trackBlock, type BusyHintProps } from "./BusyHint";

const AVAILABILITY = `${API}/availability`;
const ZHENYA: UserSummary = { id: "u2", display_name: "Женя", color: "pink" };
const DAY = "2026-11-06";
/** 19:00–20:00 in Moscow on the day. */
const EVENT = { start: "2026-11-06T16:00:00Z", end: "2026-11-06T17:00:00Z" };

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("trackBlock", () => {
  // Midnight to midnight in Moscow, as the period of the form gives it.
  const DAY_START = "2026-11-05T21:00:00Z";
  const DAY_END = "2026-11-06T21:00:00Z";

  it("places a block inside the day as percentages of it", () => {
    // 15:00–16:00 in Moscow starts 15 hours into the day.
    const block = trackBlock("2026-11-06T12:00:00Z", "2026-11-06T13:00:00Z", DAY_START, DAY_END);
    expect(block.left).toBeCloseTo(62.5);
    expect(block.width).toBeCloseTo(100 / 24);
  });

  it("clips a block that starts before the day", () => {
    // 21:00–02:00 in Moscow starts the day before; on the day it is 00:00–02:00, so it lasts 2 hours.
    const block = trackBlock("2026-11-05T18:00:00Z", "2026-11-05T23:00:00Z", DAY_START, DAY_END);
    expect(block.left).toBe(0);
    expect(block.width).toBeCloseTo((2 / 24) * 100);
  });

  it("clips a block that ends after the day", () => {
    // 23:00–04:00 in Moscow runs past midnight; on the day it is 23:00–00:00, so it lasts 1 hour.
    const block = trackBlock("2026-11-06T20:00:00Z", "2026-11-07T01:00:00Z", DAY_START, DAY_END);
    expect(block.left).toBeCloseTo((23 / 24) * 100);
    expect(block.width).toBeCloseTo(100 / 24);
  });
});

describe("overlaps", () => {
  const at = (hour: number) => `2026-11-06T${String(hour).padStart(2, "0")}:00:00Z`;

  it("is false for intervals that only touch", () => {
    expect(overlaps(at(10), at(11), at(11), at(12))).toBe(false);
    expect(overlaps(at(11), at(12), at(10), at(11))).toBe(false);
  });

  it("is true for intervals that overlap", () => {
    expect(overlaps(at(10), at(12), at(11), at(13))).toBe(true);
  });

  it("is true when one interval contains the other", () => {
    expect(overlaps(at(10), at(14), at(11), at(12))).toBe(true);
  });

  it("is false for intervals apart from each other", () => {
    expect(overlaps(at(10), at(11), at(12), at(13))).toBe(false);
  });
});

function renderHint(props: Partial<BusyHintProps> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BusyHint
        people={[ZHENYA, USER_SUMMARY]}
        day={DAY}
        start={EVENT.start}
        end={EVENT.end}
        timeZone="Europe/Moscow"
        {...props}
      />
    </QueryClientProvider>,
  );
}

/** Zhenya is busy 19:30–21:00, which overlaps the event; Sasha is busy 15:00–16:00. */
const OVERLAP_AND_FREE_LATER: UserAvailability[] = [
  {
    user_id: ZHENYA.id,
    busy: [{ start_at: "2026-11-06T16:30:00Z", end_at: "2026-11-06T18:00:00Z" }],
  },
  {
    user_id: USER_SUMMARY.id,
    busy: [{ start_at: "2026-11-06T12:00:00Z", end_at: "2026-11-06T13:00:00Z" }],
  },
];

describe("busy hint", () => {
  it("warns about the people whose busy time overlaps the event", async () => {
    stubApp({ availability: OVERLAP_AND_FREE_LATER });
    renderHint();

    expect(await screen.findByText("занято 15:00–16:00")).toBeInTheDocument();
    expect(
      screen.getByText("Пересечение по времени: Женя. Сохранить всё равно можно."),
    ).toBeInTheDocument();
  });

  it("names the people with a clash in the order of the participants", async () => {
    stubApp({
      availability: [
        { user_id: USER_SUMMARY.id, busy: [{ start_at: EVENT.start, end_at: EVENT.end }] },
        {
          user_id: ZHENYA.id,
          busy: [{ start_at: "2026-11-06T16:30:00Z", end_at: "2026-11-06T18:00:00Z" }],
        },
      ],
    });
    renderHint();

    expect(
      await screen.findByText("Пересечение по времени: Женя, Саша. Сохранить всё равно можно."),
    ).toBeInTheDocument();
  });

  it("gives no warning when busy times only touch the event", async () => {
    // Zhenya is busy 18:00–19:00, which ends exactly when the event starts.
    stubApp({
      availability: [
        {
          user_id: ZHENYA.id,
          busy: [{ start_at: "2026-11-06T15:00:00Z", end_at: "2026-11-06T16:00:00Z" }],
        },
        { user_id: USER_SUMMARY.id, busy: [] },
      ],
    });
    renderHint();

    expect(await screen.findByText("занято 18:00–19:00")).toBeInTheDocument();
    expect(screen.queryByText(/Пересечение по времени/)).not.toBeInTheDocument();
  });

  it("shows free people as free, and gives no warning when nobody is busy", async () => {
    stubApp({
      availability: [
        { user_id: ZHENYA.id, busy: [] },
        { user_id: USER_SUMMARY.id, busy: [] },
      ],
    });
    renderHint();

    expect(await screen.findAllByText("свободно")).toHaveLength(2);
    expect(screen.queryByText(/Пересечение по времени/)).not.toBeInTheDocument();
  });

  it("sends the event as excluded from the availability", async () => {
    const calls = stubApp({ availability: [] });
    renderHint({ excludeEventId: "e9" });

    await waitFor(() => expect(requestsTo(calls, "GET", AVAILABILITY)).toHaveLength(1));
    const [request] = requestsTo(calls, "GET", AVAILABILITY);
    expect(searchOf(request!).get("exclude_event_id")).toBe("e9");
  });

  it("asks for the availability of every participant", async () => {
    const calls = stubApp({ availability: [] });
    renderHint();

    await waitFor(() => expect(requestsTo(calls, "GET", AVAILABILITY)).toHaveLength(1));
    const [request] = requestsTo(calls, "GET", AVAILABILITY);
    expect(searchOf(request!).getAll("user_ids")).toEqual([ZHENYA.id, USER_SUMMARY.id]);
  });

  it("renders nothing and asks for nothing while the start is unknown", async () => {
    const calls = stubApp({ availability: OVERLAP_AND_FREE_LATER });
    const { container } = renderHint({ start: null });

    expect(container).toBeEmptyDOMElement();
    // Give a request the chance to start, which it must not.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(requestsTo(calls, "GET", AVAILABILITY)).toHaveLength(0);
  });

  it("asks up to the end of an event that runs past midnight", async () => {
    // 23:30 to 01:00 in Moscow, the second half on the next day.
    const calls = stubApp({
      availability: [
        {
          user_id: ZHENYA.id,
          busy: [{ start_at: "2026-11-06T21:15:00Z", end_at: "2026-11-06T21:45:00Z" }],
        },
        { user_id: USER_SUMMARY.id, busy: [] },
      ],
    });
    renderHint({ start: "2026-11-06T20:30:00Z", end: "2026-11-06T22:00:00Z" });

    expect(
      await screen.findByText("Пересечение по времени: Женя. Сохранить всё равно можно."),
    ).toBeInTheDocument();
    const [request] = requestsTo(calls, "GET", AVAILABILITY);
    expect(searchOf(request!).get("from")).toBe("2026-11-05T21:00:00Z");
    expect(searchOf(request!).get("to")).toBe("2026-11-06T22:00:00Z");
  });

  it("leaves out the busy times after midnight from the text of the day", async () => {
    // Zhenya's busy time, 00:15–00:45 in Moscow, is on the next day.
    stubApp({
      availability: [
        {
          user_id: ZHENYA.id,
          busy: [{ start_at: "2026-11-06T21:15:00Z", end_at: "2026-11-06T21:45:00Z" }],
        },
        { user_id: USER_SUMMARY.id, busy: [] },
      ],
    });
    renderHint({ start: "2026-11-06T20:30:00Z", end: "2026-11-06T22:00:00Z" });

    await screen.findByText("Пересечение по времени: Женя. Сохранить всё равно можно.");
    expect(screen.queryByText(/00:15/)).not.toBeInTheDocument();
    expect(screen.getAllByText("свободно")).toHaveLength(2);
  });

  it("asks for the day alone when the event ends within it", async () => {
    const calls = stubApp({ availability: [] });
    renderHint();

    await waitFor(() => expect(requestsTo(calls, "GET", AVAILABILITY)).toHaveLength(1));
    const [request] = requestsTo(calls, "GET", AVAILABILITY);
    expect(searchOf(request!).get("from")).toBe("2026-11-05T21:00:00Z");
    expect(searchOf(request!).get("to")).toBe("2026-11-06T21:00:00Z");
  });
});
