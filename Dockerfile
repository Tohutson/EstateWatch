FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    XDG_CACHE_HOME=/app/model-cache \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-cache \
    && mkdir -p /app/data /app/model-cache \
    && chown -R appuser:appuser /app/data /app/model-cache

USER appuser
VOLUME ["/app/data", "/app/model-cache"]
ENTRYPOINT ["estate-sale-finder"]
CMD ["run"]
