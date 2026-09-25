# syntax=docker/dockerfile:1

# ---- Build stage: compile wheels so the runtime image needs no compilers ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

ARG APP_VERSION=dev
ARG GIT_COMMIT=local
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="shelf" \
      org.opencontainers.image.description="Shelf library management system" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FLASK_APP=wsgi.py \
    PORT=8000

# Apply OS security patches, then drop to an unprivileged user.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system shelf && useradd --system --gid shelf --home /app shelf

WORKDIR /app
COPY --from=builder /wheels /wheels
# pip is only needed to install the wheels. Removing it (and ensurepip's bundled copy) drops
# its vendored msgpack/pkg_resources, which Trivy flagged (GHSA-6v7p-g79w-8964, CVE-2025-47273).
RUN pip install --no-cache-dir /wheels/* \
 && rm -rf /wheels \
 && pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3.12/ensurepip

# Code stays root-owned (read-only for the app user); only the working dir is writable
# because gunicorn keeps its control socket there.
COPY app ./app
COPY wsgi.py docker-entrypoint.sh ./
RUN chmod 0555 docker-entrypoint.sh && chown shelf:shelf /app

USER shelf
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
