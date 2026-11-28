# The app image: pipeline jobs, loaders and (later) the API (docs/DEPLOY.md, docs/ARCHITECTURE.md §5, §7).
# Built for linux/amd64, no GPU. Base image pinned by digest; Python packages pinned by uv.lock.
# Build-time network: base image, Debian packages, Python packages. Runtime network: the Apertus endpoint
# (LLM_BASE_URL) only; the database is reached on the cluster's internal network.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

# Stage 1: the virtual environment, without the dev tools (pytest, ruff) and without uv in the final image.
FROM ${PYTHON_IMAGE} AS deps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: the runtime. Non-root user, read-only friendly (writes go to /app/data and /app/results only).
FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_COMMIT=""
ARG GIT_DIRTY="1"
LABEL org.opencontainers.image.title="suva-nga-app" \
      org.opencontainers.image.description="Suva case-law monitoring: ingestion, layer 1, pipeline jobs" \
      org.opencontainers.image.source="https://github.com/Apertus-NGA/suva-NGA" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${GIT_COMMIT}"
# PY=python: the Makefile runs the venv's python, not uv. SUVA_GIT_*: the commit a run records when the image
# holds no .git (src/db/pg.py git_state).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PY=python \
    HOME=/home/suva \
    SUVA_GIT_COMMIT=${GIT_COMMIT} \
    SUVA_GIT_DIRTY=${GIT_DIRTY}
# make runs the targets; postgresql-client is the psql that src/db/deploy.py drives (PostgreSQL 17 client).
RUN apt-get update \
 && apt-get install -y --no-install-recommends make postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 suva \
 && useradd --system --uid 10001 --gid suva --home-dir /home/suva --create-home --shell /usr/sbin/nologin suva
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY . .
# Mount points owned by suva, so that a new named volume is writable by the jobs: /srv/hf (base dataset, fetch),
# /app/data/derived (replay caches and Suva-derived artefacts, D-031).
RUN mkdir -p /app/data/derived /app/results /srv/hf && chown -R suva:suva /app/data /app/results /srv/hf
USER suva:suva
EXPOSE 8000
CMD ["make", "run"]
