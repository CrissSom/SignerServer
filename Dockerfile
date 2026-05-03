# ── Stage 1: install AzureSignTool and patch its shim ────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS tool-builder

RUN dotnet tool install --global AzureSignTool

# The generated shim at /root/.dotnet/tools/AzureSignTool is a bash script
# with a hardcoded path like:
#   exec "dotnet" "/root/.dotnet/tools/.store/.../AzureSignTool.dll" "$@"
#
# Patch it to reference /usr/local/dotnet-tools instead so it works from any
# user when the store is copied to that world-accessible location.
RUN sed -i 's|/root/.dotnet/tools/|/usr/local/dotnet-tools/|g' \
        /root/.dotnet/tools/azuresigntool

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

# Copy the patched shim + store to the path the shim now references.
# /usr/local is world-readable (755) so any user can traverse into it.
COPY --from=tool-builder /root/.dotnet/tools /usr/local/dotnet-tools
RUN chmod -R a+rX /usr/local/dotnet-tools

ENV PATH="/usr/local/dotnet-tools:${PATH}"

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
