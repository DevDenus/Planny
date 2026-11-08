#!/usr/bin/env python3
"""Measures the response time of ordinary operations the way the browser sees it.

Requests go through the BFF (/bff/login, /bff/api/v1/...) with the session and CSRF cookies,
exactly as the SPA sends them, over one keep-alive connection like a browser tab. Run it from
another LAN device against the real domain, not from the server itself:

    python3 deploy/tools/measure_p95.py --url https://planny.roflix.site --login p95-check

Use a dedicated account: the script creates its own board, events and tasks and removes them
at the end (a board can only be archived, so it stays archived). The password comes from
PLANNY_PASSWORD or a prompt. The account must have no one-time password pending.

Exit code: 0 if the overall p95 is under the threshold, 1 if not, 2 on any error.
Standard library only, python3 >= 3.10.
"""

import argparse
import getpass
import http.client
import json
import os
import ssl
import sys
import time
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit

API = "/bff/api/v1"
TIMEOUT_SECONDS = 30
BODY_SNIPPET = 300


class ApiError(Exception):
    pass


def percentile(samples: list[float], share: float) -> float:
    # Nearest rank: the smallest value with at least `share` of the samples at or below it.
    ordered = sorted(samples)
    rank = -(-len(ordered) * share // 1)  # ceil without math
    return ordered[max(int(rank), 1) - 1]


class Client:
    def __init__(self, url: str, insecure: bool) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise SystemExit("ошибка: --url должен быть вида http(s)://хост[:порт]")
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._context = None
        if self._https and insecure:
            self._context = ssl._create_unverified_context()  # noqa: S323
        self._cookies: dict[str, str] = {}
        self._conn: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._conn is None:
            if self._https:
                self._conn = http.client.HTTPSConnection(
                    self._host, self._port, timeout=TIMEOUT_SECONDS, context=self._context
                )
            else:
                self._conn = http.client.HTTPConnection(
                    self._host, self._port, timeout=TIMEOUT_SECONDS
                )
        return self._conn

    def _csrf(self) -> str | None:
        for name, value in self._cookies.items():
            if name.endswith("planny_csrf"):
                return value
        return None

    def _send(self, method: str, path: str, body: bytes | None, headers: dict[str, str]):
        # A keep-alive connection the server has closed is reopened once, outside the timing.
        for attempt in (1, 2):
            conn = self._connect()
            try:
                started = time.perf_counter()
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                data = response.read()
                return response, data, (time.perf_counter() - started) * 1000
            except ConnectionError:  # includes RemoteDisconnected and BrokenPipeError
                conn.close()
                self._conn = None
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def request(self, method: str, path: str, payload=None) -> tuple[object, float]:
        """Returns the decoded JSON body (None if empty) and the elapsed milliseconds."""
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if self._cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        if method not in {"GET", "HEAD"} and (token := self._csrf()):
            headers["X-CSRF-Token"] = token
        try:
            response, data, elapsed = self._send(method, path, body, headers)
        except (OSError, http.client.HTTPException) as error:
            raise ApiError(f"{method} {path}: нет ответа ({error})") from None
        for header in response.headers.get_all("Set-Cookie") or []:
            jar: SimpleCookie = SimpleCookie()
            jar.load(header)
            for name, morsel in jar.items():
                if morsel.value:
                    self._cookies[name] = morsel.value
                else:
                    self._cookies.pop(name, None)
        if response.status >= 400:
            snippet = data.decode("utf-8", "replace")[:BODY_SNIPPET]
            raise ApiError(f"{method} {path}: HTTP {response.status} {snippet}")
        return (json.loads(data) if data else None), elapsed

    def login(self, login: str, password: str) -> None:
        try:
            self.request("POST", "/bff/login", {"login": login, "password": password})
        except ApiError as error:
            # The message carries a response body, never the request, so no secrets leak.
            raise ApiError(f"вход не удался: {error}") from None
        if not self._csrf():
            raise ApiError("вход не удался: сервер не выдал CSRF cookie")

    def logout(self) -> None:
        self.request("POST", "/bff/logout")


def week_range() -> tuple[datetime, datetime]:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=7)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class Run:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.samples: dict[str, list[float]] = {}
        self.recording = False
        self.board_id = ""
        self.columns: list[str] = []
        self.events: set[str] = set()
        self.tasks: set[str] = set()

    def timed(self, label: str, method: str, path: str, payload=None):
        data, elapsed = self.client.request(method, path, payload)
        if self.recording:
            self.samples.setdefault(label, []).append(elapsed)
        return data

    def setup(self) -> None:
        board, _ = self.client.request(
            "POST", f"{API}/boards", {"name": f"p95-{datetime.now(UTC):%Y%m%d-%H%M%S}"}
        )
        self.board_id = board["id"]  # type: ignore[index]
        columns, _ = self.client.request("GET", f"{API}/boards/{self.board_id}/columns")
        self.columns = [column["id"] for column in columns["items"]]  # type: ignore[index]
        if len(self.columns) < 2:
            raise ApiError("на новой доске меньше двух колонок")

    def one_round(self) -> None:
        start, end = week_range()
        window = urlencode({"from": stamp(start), "to": stamp(end)})
        self.timed("Опрос sync", "GET", f"{API}/sync")
        self.timed("Текущий пользователь", "GET", f"{API}/me")
        self.timed("Календарь на неделю", "GET", f"{API}/calendar/items?{window}")
        boards = self.timed("Список досок", "GET", f"{API}/boards")
        first = boards["items"][0]["id"]  # the dedicated board exists, so the list is not empty
        tasks = urlencode({"board_id": first, "status": "all", "sort": "position", "limit": 100})
        self.timed("Задачи доски", "GET", f"{API}/tasks?{tasks}")

        noon = start + timedelta(days=2, hours=12)
        event = self.timed(
            "Событие: создание",
            "POST",
            f"{API}/events",
            {
                "title": "p95 проверка",
                "all_day": False,
                "start_at": stamp(noon),
                "end_at": stamp(noon + timedelta(hours=1)),
                "timezone": "UTC",
            },
        )
        self.events.add(event["id"])
        self.timed(
            "Событие: изменение",
            "PATCH",
            f"{API}/events/{event['id']}",
            {"version": event["version"], "title": "p95 проверка 2"},
        )
        self.timed("Событие: удаление", "DELETE", f"{API}/events/{event['id']}")
        self.events.discard(event["id"])

        task = self.timed(
            "Задача: создание",
            "POST",
            f"{API}/tasks",
            {"title": "p95 проверка", "board_id": self.board_id, "column_id": self.columns[0]},
        )
        self.tasks.add(task["id"])
        self.timed(
            "Задача: перенос",
            "POST",
            f"{API}/tasks/{task['id']}/move",
            {"column_id": self.columns[1]},
        )
        self.timed("Задача: удаление", "DELETE", f"{API}/tasks/{task['id']}")
        self.tasks.discard(task["id"])

    def cleanup(self) -> list[str]:
        """Best effort, returns what could not be removed."""
        left: list[str] = []
        for kind, ids in (("events", self.events), ("tasks", self.tasks)):
            for item_id in sorted(ids):
                try:
                    self.client.request("DELETE", f"{API}/{kind}/{item_id}")
                except ApiError as error:
                    left.append(f"{kind}/{item_id}: {error}")
        if self.board_id:
            try:
                board, _ = self.client.request("GET", f"{API}/boards/{self.board_id}")
                self.client.request(
                    "PATCH",
                    f"{API}/boards/{self.board_id}",
                    {"version": board["version"], "archived": True},  # type: ignore[index]
                )
            except ApiError as error:
                left.append(f"boards/{self.board_id}: {error}")
        return left


def report(samples: dict[str, list[float]], threshold: float) -> int:
    width = max(len(label) for label in samples)
    print(f"{'Операция':<{width}}  {'n':>4}  {'p50':>8}  {'p95':>8}  {'max':>8}  (мс)")
    everything: list[float] = []
    for label, values in samples.items():
        everything += values
        print(
            f"{label:<{width}}  {len(values):>4}  {percentile(values, 0.5):>8.1f}"
            f"  {percentile(values, 0.95):>8.1f}  {max(values):>8.1f}"
        )
    overall = percentile(everything, 0.95)
    print(f"\nВсего запросов: {len(everything)}, общий p95: {overall:.1f} мс")
    if overall < threshold:
        print(f"Итог: норма, p95 {overall:.1f} мс меньше порога {threshold:.0f} мс")
        return 0
    print(f"Итог: медленно, p95 {overall:.1f} мс не меньше порога {threshold:.0f} мс")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="p95 обычных операций через BFF.")
    parser.add_argument(
        "--url", required=True, help="адрес BFF, например https://planny.roflix.site"
    )
    parser.add_argument("--login", required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--threshold-ms", type=float, default=500)
    parser.add_argument(
        "--insecure", action="store_true", help="не проверять TLS, только для тестов"
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations должно быть больше нуля")

    password = os.environ.get("PLANNY_PASSWORD") or getpass.getpass("Пароль: ")
    client = Client(args.url, args.insecure)
    run = Run(client)
    status = 2
    try:
        client.login(args.login, password)
        run.setup()
        run.one_round()  # warm-up: connection, TLS, caches, not counted
        run.recording = True
        for _ in range(args.iterations):
            run.one_round()
        status = report(run.samples, args.threshold_ms)
    except ApiError as error:
        print(f"ошибка: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("прервано", file=sys.stderr)
    finally:
        left = run.cleanup() if run.board_id else []
        for item in left:
            print(f"не удалось убрать: {item}", file=sys.stderr)
        try:
            client.logout()
        except ApiError as error:
            print(f"выход не удался: {error}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
