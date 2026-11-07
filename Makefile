COMPOSE = docker compose --project-directory deploy -f deploy/compose.yaml -f deploy/compose.dev.yaml
TEST_COMPOSE = docker compose -f deploy/compose.test.yaml
# -p because `down -v` must never follow a COMPOSE_PROJECT_NAME from the shell to the dev volume.
E2E_COMPOSE = docker compose -p planny-e2e --project-directory deploy -f deploy/compose.yaml -f deploy/compose.e2e.yaml

.PHONY: env up down db-reset logs migration test-db test test-backend test-bff test-web e2e restore-check trial-restore release lint format openapi client

deploy/.env:
	@umask 077; { \
		echo "POSTGRES_PASSWORD=$$(openssl rand -hex 32)"; \
		echo "BFF_SHARED_SECRET=$$(openssl rand -hex 32)"; \
		echo "COOKIE_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')"; \
		echo "COOKIE_SECURE=false"; \
		echo "TRUST_FORWARDED_FOR=false"; \
	} > $@
	@echo "Wrote $@"

env: deploy/.env

up: deploy/.env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

# Recreates the dev database from the migrations: everything in it is lost.
db-reset: deploy/.env
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build --wait

logs:
	$(COMPOSE) logs -f

# A new migration from the difference between the models and the dev database, which must be at
# head (`make up`). Review the generated file: autogenerate misses raw SQL and some renames.
migration: deploy/.env
	@test -n "$(name)" || { echo "usage: make migration name=add_something" >&2; exit 1; }
	$(COMPOSE) run --rm --build --user "$$(id -u):$$(id -g)" \
		-v "$(CURDIR)/backend/migrations/versions:/app/migrations/versions" \
		migrate alembic revision --autogenerate -m "$(name)"

test-db:
	$(TEST_COMPOSE) up -d --wait

test: test-backend test-bff test-web

e2e: deploy/.env
	$(E2E_COMPOSE) up -d --build --wait
	cd web && npx playwright test; status=$$?; cd .. && $(E2E_COMPOSE) down -v; exit $$status

# AC-11 on a throwaway stack: damaged copies change nothing, a good one restores.
restore-check: deploy/.env
	deploy/backup/check-restore.sh

# The newest dump restored into a throwaway project and read by the current images. The server
# runs the same script weekly from a systemd timer.
trial-restore: deploy/.env
	deploy/backup/trial-restore.sh

# A release for the server: both images and the deploy files in dist/planny-$(VERSION).tar.
release:
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=0.1.0" >&2; exit 1; }
	deploy/release.sh "$(VERSION)"

test-backend: test-db
	cd backend && uv run pytest

test-bff:
	cd bff && uv run pytest

test-web:
	cd web && npm test

lint:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy
	cd bff && uv run ruff format --check . && uv run ruff check . && uv run mypy
	cd web && npm run lint && npm run typecheck

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd bff && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format

# Regenerates the contract and the TypeScript client from it.
openapi:
	cd backend && uv run python scripts/export_openapi.py
	$(MAKE) client

client:
	cd web && npm run gen:api
