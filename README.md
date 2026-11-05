# Planny

Self-hosted calendar app for family usage.

Закрытый планировщик для одной семьи. Документация лежит в [docs/](docs/README.md).

## Что нужно

- Docker с Compose.
- `uv`, `make` и Node 24 (версия указана в `web/.nvmrc`) для тестов и линтеров. Для запуска приложения хватает Docker.

## Запуск

```bash
make up
```

Команда при первом запуске создаёт `deploy/.env` со случайными секретами, собирает образы и поднимает всё в Compose. Сайт открывается на <http://localhost:8080>. API слушает только `127.0.0.1:8000`, а база не опубликована вовсе.

Регистрации нет, первого пользователя создаёт оператор. Команда выведет одноразовый пароль, при первом входе его нужно сменить.

```bash
docker compose --project-directory deploy -f deploy/compose.yaml -f deploy/compose.dev.yaml exec api planny users create sasha --name "Саша"
```

Остальные команды оператора описаны в [api.md](docs/api.md#6-cli), резервные копии в [deploy/backup/README.md](deploy/backup/README.md).

## Разработка

| Команда | Что делает |
|---|---|
| `make test` | Тесты backend, BFF и SPA. Для backend сама поднимает одноразовую PostgreSQL |
| `make e2e` | Сценарии в браузере на отдельном стеке со своей базой. Нужны Docker и `npx playwright install chromium` в `web/` |
| `make restore-check` | Копия и восстановление на отдельном стеке, включая повреждённые копии |
| `make lint` | Форматирование, линтеры и проверка типов |
| `make format` | Исправляет форматирование |
| `make openapi` | Обновляет `backend/openapi.json` и клиент API в `web/src/api/`. Нужна после изменения маршрутов, иначе CI упадёт |
| `make logs` | Логи контейнеров |
| `make down` | Останавливает контейнеры, данные остаются в томе |
| `make db-reset` | Пересоздаёт базу разработки после изменения схемы, все данные в ней теряются |

Для работы над интерфейсом удобнее `npm run dev` в папке `web/`: Vite открывается на <http://localhost:5173> и проксирует `/bff` в запущенный Compose.
