# ── Stage 1: install AzureSignTool via .NET SDK ───────────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS tool-builder

RUN dotnet tool install --global AzureSignTool

# ── Stage 2: runtime image ────────────────────────────────────────────────────
# Use the .NET runtime image so `dotnet` is on PATH — the global tool shim
# script has hardcoded references to /root/.dotnet/tools/.store/... and calls
# `dotnet` to run the DLL, so both the path and the runtime must be present.
FROM mcr.microsoft.com/dotnet/runtime:8.0-bookworm-slim

LABEL org.opencontainers.image.title="Windows Binary Signing Server"
LABEL org.opencontainers.image.description="Authenticode signing via Azure Key Vault"

# Install Python 3.11 (latest available on Debian 12)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Copy tool store to the SAME path it was installed at.
# The shim at /root/.dotnet/tools/AzureSignTool contains a hardcoded reference
# to /root/.dotnet/tools/.store/... — moving it to any other path breaks it.
COPY --from=tool-builder /root/.dotnet/tools /root/.dotnet/tools
RUN chmod -R a+rX /root/.dotnet/tools
ENV PATH="/root/.dotnet/tools:${PATH}"

WORKDIR /app

# Use a virtualenv to avoid PEP 668 conflicts with the system Python
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8080

RUN useradd -m -u 1000 signer
USER signer

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
