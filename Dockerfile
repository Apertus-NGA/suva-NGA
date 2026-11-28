# The app image (docs/ARCHITECTURE.md §5). Built for linux/amd64, no GPU. Base pinned by digest.
# Build-time network: base image, Python packages (uv.lock). Runtime network: the Apertus endpoint, and
# Hugging Face for `suva_data pull` when the database is empty and no data/snapshot is mounted.
# Runtime packages only: the dev and research groups (pytest, torch via sentence-transformers) stay out.
# The UI: the image has no Node, so it serves the API only, unless src/web/dist was built on the host before
# `docker compose build` (COPY . . then carries it in; `make serve` on the host builds it).
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PY=python

RUN apt-get update \
 && apt-get install -y --no-install-recommends make \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.13.6

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Dependencies first (a cached layer), then the source, then the project itself (needs the source).
RUN uv sync --frozen --no-default-groups --no-install-project
COPY . .
RUN uv sync --frozen --no-default-groups

# Inside the container the server listens on every interface; compose publishes it on 127.0.0.1 only.
ENV SUVA_HOST=0.0.0.0
EXPOSE 8000
CMD ["make", "run"]
