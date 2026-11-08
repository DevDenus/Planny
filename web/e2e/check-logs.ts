import { execFileSync } from "node:child_process";

import { COMPOSE, PASSWORD } from "./support";

const MAX_LOG_BYTES = 200 * 1024 * 1024;
/** All the content of the tests is in Russian, so a Cyrillic letter in a log is a leak by itself. */
const FORBIDDEN: [string, RegExp][] = [
  ["личное содержимое", /\p{Script=Cyrillic}/u],
  ["пароль", new RegExp(PASSWORD)],
  ["логин", /\be2e\d{5,}/],
  ["заголовок авторизации", /Bearer /],
  ["cookie", /planny_(session|csrf)/],
  ["строка запроса", /[?&](q|login|password)=/],
];

/** Runs once after every test, while the stack is still up: see the logs line in docs/features.md. */
export default function checkLogs(): void {
  const logs = execFileSync("docker", [...COMPOSE, "logs", "--no-color", "--no-log-prefix"], {
    encoding: "utf8",
    maxBuffer: MAX_LOG_BYTES,
  });
  if (!logs.includes('"logger": "planny.bff"') || !logs.includes('"logger": "planny.request"')) {
    throw new Error("в логах нет строк BFF и API: проверять нечего");
  }
  const lines = logs.split("\n");
  const found = FORBIDDEN.flatMap(([name, pattern]) =>
    lines.filter((line) => pattern.test(line)).map((line) => `${name}: ${line.slice(0, 300)}`),
  );
  if (found.length > 0) {
    throw new Error(`в логах ${found.length} запрещённых строк:\n${found.slice(0, 20).join("\n")}`);
  }
}
