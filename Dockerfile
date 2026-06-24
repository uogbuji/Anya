# syntax=docker/dockerfile:1
#
# anya — headless LLM agent runner, packaged for single-host Docker Compose deploy.
# See doc.DEPLOYMENT.md for the full workflow (remote context, secrets, job selection).

############################################################
# Builder: build the anya wheel and install it (non-editable)
# into a relocatable venv. We test/ship the real distribution,
# never an editable / source-on-path install.
############################################################
FROM python:3.12-slim AS builder

# Build tooling: build-essential for any sdist-only wheel, git for VCS dependencies
# (ogbujipt is pinned to git main until release).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
ENV UV_LINK_MODE=copy

WORKDIR /src
# Copy only what the build needs first, so editing a job or config below does not
# bust this (expensive) dependency-install layer.
COPY pyproject.toml README.md ./
COPY pylib ./pylib

# `uv pip install .` builds the wheel and installs it non-editably into the venv.
RUN uv venv /opt/venv \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache ".[scheduler-apscheduler]"

############################################################
# Runtime: slim image with just the venv + selected jobs + config.
############################################################
FROM python:3.12-slim AS runtime

# Least privilege: run the scheduler as a non-root user that only writes under /app/data.
RUN useradd --create-home --uid 10001 anya

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Shared HTTP cache lives on the persisted data volume (good HTTP citizen across rebuilds).
    ANYA_HTTP_CACHE=/app/data/http-cache.sqlite

WORKDIR /app

# config.toml is a sensible baked-in default (model aliases/backends the image was built
# against). Mount your own over /app/config.toml to override without a rebuild.
COPY config.toml ./config.toml

# Jobs and persistent state are NOT baked in — they are deployer-curated host content,
# bind-mounted at runtime (see compose.yml / doc.DEPLOYMENT.md):
#   /app/job   <- the curated job dir   (anya serve refuses to start if it's empty/missing)
#   /app/data  <- blotter, memory, HTTP cache, and per-job state (persists across rebuilds)
# The image is a generic anya runtime; changing jobs is a remount, not a rebuild.
RUN mkdir -p /app/job /app/data && chown -R anya:anya /app

USER anya

# Sanity gate: the image imports cleanly and the baked config parses. (anya serve has no
# inbound port, so this is an image-health signal, not a liveness probe for a server.)
HEALTHCHECK --interval=1m --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import anya, tomllib; tomllib.load(open('/app/config.toml','rb'))" || exit 1

ENTRYPOINT ["anya"]
# Overridden by compose; sane default if run bare.
CMD ["serve", "--interval=86400"]
