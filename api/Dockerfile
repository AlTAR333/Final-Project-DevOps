# syntax=docker/dockerfile:1
# Owner: Armand. Multistage, non-root, minimal runtime.
# Build from repo root: docker build -f api/Dockerfile -t fulfillops-api:<sha> .
#
# The image ships common/ and api/, plus db/ because the same image runs the migration step
# (`python -m db.migrate`) in Compose and in the Kubernetes migrate Job.
#
# Base image: the Python minor version is pinned (same as CI). The patch/OS layers are taken
# from upstream's latest rebuild so the image scan stays clean; for a bit-for-bit reproducible
# build, pin the digest: --build-arg PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:<digest>
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---- build stage: install pinned dependencies into a virtualenv ---------------------------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY api/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt
RUN /opt/venv/bin/python -m pip uninstall -y pip

# ---- runtime stage: no compiler, no pip cache, no build tools in the final layers ---------
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_PORT=8080

RUN python -m pip uninstall -y pip

# Fixed numeric uid/gid: Kubernetes runAsNonRoot needs a number, and it matches infra/k8s.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# Code stays owned by root and read-only for the app user.
COPY common/ common/
COPY api/ api/
COPY db/ db/

USER 10001:10001
EXPOSE 8080

# Process-level check only (liveness never touches the database). Compose and Kubernetes
# add their own readiness checks on /health/ready.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('API_PORT', '8080'), timeout=2)"]

CMD ["python", "-m", "api.app"]
