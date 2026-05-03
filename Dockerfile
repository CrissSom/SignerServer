# ── Stage 1: install AzureSignTool as the signer user ────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS tool-builder

# Create the same non-root user so the tool installs into /home/signer/.dotnet/tools.
# The shim script records the install path, so the final image must use the same path.
RUN useradd -m -u 1000 signer
USER signer
RUN dotnet tool install --global AzureSignTool

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

# Recreate signer user with the same UID as the builder stage
RUN useradd -m -u 1000 signer

# Copy tool store to the same path it was installed at so the shim's hardcoded
# /home/signer/.dotnet/tools/.store/... reference resolves correctly
COPY --from=tool-builder --chown=signer:signer \
    /home/signer/.dotnet/tools /home/signer/.dotnet/tools

ENV PATH="/home/signer/.dotnet/tools:${PATH}"

WORKDIR /app

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
RUN chown -R signer:signer /app

EXPOSE 8080

USER signer

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
