# One image runs as API, worker, CLI and migrations, only the command differs.
FROM python:3.14-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim
RUN useradd --system --uid 10001 --no-create-home planny
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER planny
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
