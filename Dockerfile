# ── Stage 1: install AzureSignTool to an explicit path ───────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS tool-builder

# Install to /opt/dotnet-tools so the shim's hardcoded .store reference points
# to /opt/dotnet-tools/.store/... — a path we can copy verbatim to the final
# image without any home-directory or user ownership complications.
RUN dotnet tool install AzureSignTool --tool-path /opt/dotnet-tools

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM mcr.microsoft.com/dotnet/runtime:8.0-bookworm-slim

LABEL org.opencontainers.image.title="Windows Binary Signing Server"
LABEL org.opencontainers.image.description="Authenticode signing via Azure Key Vault"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Copy tool to the SAME path — shim contains hardcoded /opt/dotnet-tools/.store/...
COPY --from=tool-builder /opt/dotnet-tools /opt/dotnet-tools
RUN chmod -R a+rX /opt/dotnet-tools

ENV PATH="/opt/dotnet-tools:${PATH}"

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
