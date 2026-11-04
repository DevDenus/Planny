COMPOSE = docker compose --project-directory deploy -f deploy/compose.yaml -f deploy/compose.dev.yaml
TEST_COMPOSE = docker compose -f deploy/compose.test.yaml

.PHONY: env up down logs test-db test test-backend test-bff test-web lint format openapi client

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

logs:
	$(COMPOSE) logs -f

test-db:
	$(TEST_COMPOSE) up -d --wait

test: test-backend test-bff test-web

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
