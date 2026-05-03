# ── Stage 1: install AzureSignTool via .NET SDK ───────────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS tool-builder

# Install the latest AzureSignTool as a self-contained global tool
RUN dotnet tool install --global AzureSignTool

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Windows Binary Signing Server"
LABEL org.opencontainers.image.description="Authenticode signing via Azure Key Vault"

# Copy AzureSignTool binary from builder stage
COPY --from=tool-builder /root/.dotnet/tools /opt/dotnet-tools

# Install .NET runtime (required to run AzureSignTool)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        wget \
        apt-transport-https \
        ca-certificates \
    && wget -q https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O /tmp/ms.deb \
    && dpkg -i /tmp/ms.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends dotnet-runtime-8.0 \
    && rm -rf /var/lib/apt/lists/* /tmp/ms.deb

ENV PATH="/opt/dotnet-tools:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8080

# Run as non-root
RUN useradd -m -u 1000 signer
USER signer

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
