# Windows Binary Signing Server

A Linux-based HTTP server that signs Windows PE binaries (EXE, DLL, MSI, CAB, …) using **Authenticode** via **Azure Key Vault**. The private key never leaves Key Vault — only the file hash is sent for signing.

## Architecture

```
Client  ──POST /sign──►  FastAPI server (Linux)  ──hash──►  Azure Key Vault
                                │                          (private key stays here)
                         AzureSignTool                           │
                                │◄──────────── signature ────────┘
                         signed binary
                                │
Client  ◄── signed file ────────┘
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Azure Key Vault | Must contain a **certificate** (RSA or EC) with key usage for signing |
| Azure credentials | Service principal **or** managed identity with `Key Vault Certificate User` + `Key Vault Crypto User` roles |
| Docker (recommended) | Or: Linux host with .NET 8 SDK + Python 3.12 |

## Quick start with Docker

```bash
# 1. Copy and edit the environment file
cp .env.example .env
$EDITOR .env

# 2. Build and run
docker compose up -d

# 3. Verify the server is healthy
curl http://localhost:8080/health
```

## Quick start without Docker

```bash
# Install AzureSignTool (requires root / sudo)
sudo bash scripts/install_azuresigntool.sh

# Install Python dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
$EDITOR .env

# Run
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Configuration

All configuration is via environment variables (or a `.env` file).

| Variable | Required | Description |
|---|---|---|
| `KEY_VAULT_URL` | Yes | `https://<vault>.vault.azure.net/` |
| `CERTIFICATE_NAME` | Yes | Name of the certificate in Key Vault |
| `TENANT_ID` | No* | Azure AD tenant ID |
| `CLIENT_ID` | No* | Service principal / app client ID |
| `CLIENT_SECRET` | No* | Service principal secret |
| `API_KEY` | No | Shared secret for `X-API-Key` header auth |
| `DEFAULT_TIMESTAMP_URL` | No | RFC-3161 server (default: DigiCert) |
| `DEFAULT_TIMESTAMP_DIGEST` | No | `sha256` (default), `sha384`, `sha512` |
| `MAX_UPLOAD_BYTES` | No | Max file size (default: 200 MB) |
| `AZURE_SIGN_TOOL_PATH` | No | Path to `AzureSignTool` binary |

\* Leave blank to use managed identity (when running on Azure).

## Azure setup

### 1 — Create or import a code-signing certificate

```bash
az keyvault certificate create \
  --vault-name <vault> \
  --name <cert-name> \
  --policy "$(az keyvault certificate get-default-policy)"
```

For production, import an EV or OV code-signing certificate from a CA.

### 2 — Grant the service principal access

```bash
# Using RBAC (recommended)
az role assignment create \
  --role "Key Vault Certificate User" \
  --assignee <client-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.KeyVault/vaults/<vault>

az role assignment create \
  --role "Key Vault Crypto User" \
  --assignee <client-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.KeyVault/vaults/<vault>
```

## API

Interactive docs available at `http://localhost:8080/docs`.

### `GET /health`

Returns server status and tool version.

```json
{
  "status": "ok",
  "key_vault_url": "https://my-vault.vault.azure.net/",
  "certificate_name": "my-cert",
  "azure_sign_tool_version": "5.0.0"
}
```

### `POST /sign`

Upload a binary and receive the signed copy.

**Headers**
```
X-API-Key: <your-api-key>
Content-Type: multipart/form-data
```

**Form fields**
| Field | Type | Description |
|---|---|---|
| `file` | file | Binary to sign |

**Query parameters**
| Parameter | Description |
|---|---|
| `description` | Text shown in the Authenticode dialog |
| `description_url` | URL shown in the Authenticode dialog |
| `timestamp_url` | Override the RFC-3161 timestamp server |
| `timestamp_digest` | `sha256` / `sha384` / `sha512` |
| `certificate_name` | Override the default certificate |
| `append` | `true` to append rather than replace an existing signature |

**Example — curl**
```bash
curl -X POST http://localhost:8080/sign \
  -H "X-API-Key: change-me-to-a-strong-random-secret" \
  -F "file=@MyApp.exe" \
  -G --data-urlencode "description=My Application" \
  --output MyApp-signed.exe
```

**Example — Python**
```python
import requests

with open("MyApp.exe", "rb") as f:
    resp = requests.post(
        "http://localhost:8080/sign",
        headers={"X-API-Key": "change-me-to-a-strong-random-secret"},
        files={"file": ("MyApp.exe", f, "application/octet-stream")},
        params={"description": "My Application"},
    )
    resp.raise_for_status()

with open("MyApp-signed.exe", "wb") as out:
    out.write(resp.content)
```

## Security notes

- Always set a strong `API_KEY` in production.
- Run behind TLS (nginx / Caddy reverse proxy, or a load balancer).
- Use managed identity instead of client secrets where possible.
- The private key never leaves Azure Key Vault.
- Temp files are written to `/tmp` and deleted immediately after signing.
