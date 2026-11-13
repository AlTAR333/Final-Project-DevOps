# syntax=docker/dockerfile:1
# Owner: Armand. Multistage, non-root, minimal runtime.
# Build from repo root: docker build -f worker/Dockerfile -t fulfillops-worker:<sha> .
# The image ships common/ and worker/ only. See api/Dockerfile for the base-image policy.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---- build stage ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY worker/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt
RUN /opt/venv/bin/python -m pip uninstall -y pip

# ---- runtime stage -------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip uninstall -y pip

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY common/ common/
COPY worker/ worker/

USER 10001:10001
# Health endpoint of the worker (worker/health.py, HEALTH_PORT).
EXPOSE 8081

# 503 only when the worker loop has stopped beating for two leases.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health/live', timeout=2)"]

# `python -m worker.main` handles SIGTERM itself (finishes the current job, then exits).
CMD ["python", "-m", "worker.main"]
