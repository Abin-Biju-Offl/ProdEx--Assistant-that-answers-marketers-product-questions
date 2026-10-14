# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/models \
    TIKTOKEN_CACHE_DIR=/app/.tiktoken \
    PATH="/app/.venv/bin:$PATH" \
    GITLEAKS_VERSION=8.24.3 \
    GITLEAKS_SHA256=9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c

# uv + gitleaks. gitleaks is pinned and checksum-verified: an unscanned index is a
# security failure, so a bad download must break the build rather than build on.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -sSfL -o /tmp/gitleaks.tar.gz \
         "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    && echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && rm /tmp/gitleaks.tar.gz \
    && gitleaks version \
    && curl -sSfL https://astral.sh/uv/install.sh | sh -s -- --no-modify-path \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer is cached separately from the source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && uv run --no-sync python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY app ./app
COPY eval ./eval
COPY fixtures ./fixtures
COPY db ./db
COPY tests ./tests
# Shipped so the running container can show exactly which settings exist.
# .env itself is never copied: secrets come from the environment.
COPY .env.example ./.env.example

# Non-root runtime user
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin prodex \
    && mkdir -p /models /app/data \
    && chown -R prodex:prodex /app /models
USER prodex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]