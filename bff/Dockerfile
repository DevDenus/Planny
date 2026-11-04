# Build context is the repository root: the image carries the built SPA, so Node is not
# needed at runtime.
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.14-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /app
COPY bff/pyproject.toml bff/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY bff/app ./app
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim
RUN useradd --system --uid 10001 --no-create-home planny
WORKDIR /app
COPY --from=build /app /app
COPY --from=web /web/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER planny
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
