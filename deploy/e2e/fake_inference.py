"""A stand-in for the language model and the speech recognition in `make e2e`.

Answers the two OpenAI-style calls of the assistant with canned cards, chosen by a phrase in the
user's message. It writes no logs: the tests check that no personal text reaches them.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOMORROW = re.compile(r"^(\d{4}-\d{2}-\d{2}) \S+ — завтра$", re.MULTILINE)

BLANK = {
    "kind": "none",
    "title": "",
    "description": "",
    "board": None,
    "column": None,
    "people": [],
    "priority": 3,
    "checklist": [],
    "all_day": False,
    "date": None,
    "time": None,
    "end_date": None,
    "end_time": None,
    "location": None,
    "repeat": "none",
    "repeat_until": None,
    "repeat_count": None,
    "reminders": [],
    "reply": "Не понял",
}


def answer(prompt: str) -> dict:
    match = TOMORROW.search(prompt)
    tomorrow = match.group(1) if match else None
    text = prompt.rsplit("Сообщение пользователя:\n", 1)[-1].strip().lower()
    if "перенеси" in text:
        return BLANK | {
            "kind": "event",
            "title": "Ужин",
            "date": tomorrow,
            "time": "20:00",
            "reminders": [60],
            "reply": "Перенёс на 20:00",
        }
    if "молоко" in text:
        return BLANK | {
            "kind": "task",
            "title": "Купить молоко",
            "date": tomorrow,
            "checklist": ["Молоко 3,2%"],
            "reply": "Заполнил задачу",
        }
    if "ужин" in text:
        return BLANK | {
            "kind": "event",
            "title": "Ужин",
            "date": tomorrow,
            "time": "19:00",
            "reminders": [60],
            "reply": "Заполнил событие",
        }
    return BLANK


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/chat/completions"):
            messages = json.loads(body)["messages"]
            reply = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                answer(messages[-1]["content"]), ensure_ascii=False
                            )
                        }
                    }
                ]
            }
        elif self.path.endswith("/audio/transcriptions"):
            reply = {"text": "Купить молоко завтра"}
        else:
            self.send_error(404)
            return
        data = json.dumps(reply, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
