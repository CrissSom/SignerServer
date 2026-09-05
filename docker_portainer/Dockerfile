# Global, so both stages can see it: the builder downloads this version and the
# runtime reports it on /health. jsign itself has no --version flag.
ARG JSIGN_VERSION=6.0

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder: python deps + jsign download (kept out of the final image)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ARG JSIGN_VERSION
ARG JSIGN_SHA256=05ca18d4ab7b8c2183289b5378d32860f0ea0f3bdab1f1b8cae5894fb225fa8a

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && wget -q "https://github.com/ebourg/jsign/releases/download/${JSIGN_VERSION}/jsign-${JSIGN_VERSION}.jar" \
            -O /opt/jsign.jar \
    && echo "${JSIGN_SHA256}  /opt/jsign.jar" | sha256sum -c - \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ARG JSIGN_VERSION

LABEL org.opencontainers.image.title="Windows Binary Signing Server" \
      org.opencontainers.image.description="Authenticode signing for Windows PE binaries via Azure Key Vault" \
      org.opencontainers.image.source="https://github.com/CrissSom/SignerServer" \
      org.opencontainers.image.licenses="MIT"

# Java runs jsign; osslsigncode strips any pre-existing signature before re-signing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        default-jre-headless \
        osslsigncode \
    && rm -rf /var/lib/apt/lists/*

# Temp workspace. Uploads are buffered here, so it is kept off the container's
# writable layer and given to the unprivileged user. Declaring it before the
# volume is mounted means a named volume inherits this ownership.
ENV TMPDIR=/data/tmp \
    JSIGN_PATH=/opt/jsign.jar \
    JSIGN_VERSION=${JSIGN_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/venv/bin:${PATH}"

RUN useradd --create-home --uid 1000 signer \
    && mkdir -p /data/tmp \
    && chown -R signer:signer /data

WORKDIR /app

COPY --from=builder /opt/jsign.jar /opt/jsign.jar
COPY --from=builder --chown=signer:signer /app/venv /app/venv
COPY --chown=signer:signer app/ ./app/
COPY --chown=signer:signer docker_portainer/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

USER signer

# Portainer surfaces this as the container's health badge.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python3 -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8080'), timeout=5).status == 200 else 1)"

# The entrypoint execs uvicorn, so uvicorn is PID 1 and receives SIGTERM
# directly. Compose sets `init: true` for zombie reaping.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
