FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Windows Binary Signing Server"
LABEL org.opencontainers.image.description="Authenticode signing via Azure Key Vault"

ARG JSIGN_VERSION=6.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jre-headless \
        wget \
        ca-certificates \
    && wget -q "https://github.com/ebourg/jsign/releases/download/${JSIGN_VERSION}/jsign-${JSIGN_VERSION}.jar" \
           -O /opt/jsign.jar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 signer \
    && chown -R signer:signer /app

EXPOSE 8080

USER signer

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
