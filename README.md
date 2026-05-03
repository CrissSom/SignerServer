# Windows Binary Signing Server

A Linux-based HTTP server that signs Windows PE binaries (EXE, DLL, MSI, CAB, APPX, …) using **Authenticode** via **Azure Key Vault**. The private key never leaves Key Vault — only the file hash is sent for signing.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Prerequisites](#prerequisites)
3. [Azure setup](#azure-setup)
4. [Deployment — Docker with systemd (recommended)](#deployment--docker-with-systemd-recommended)
5. [Deployment — bare metal](#deployment--bare-metal)
6. [Configuration reference](#configuration-reference)
7. [Putting it behind TLS with nginx](#putting-it-behind-tls-with-nginx)
8. [API reference](#api-reference)
9. [Client usage examples](#client-usage-examples)
10. [Verifying a signature](#verifying-a-signature)
11. [Troubleshooting](#troubleshooting)
12. [Security notes](#security-notes)

---

## How it works

```
Client
  │
  │  POST /sign  (multipart, binary file)
  ▼
FastAPI server  (Linux host / Docker)
  │
  │  1. Saves upload to /tmp
  │  2. Invokes AzureSignTool
  │
  ▼
AzureSignTool
  │
  │  3. Fetches public certificate from Key Vault
  │  4. Computes PE hash locally
  │  5. Sends hash to Key Vault Sign API  ◄─── private key stays here
  │  6. Key Vault returns raw signature
  │  7. AzureSignTool embeds Authenticode signature + RFC-3161 timestamp
  │
  ▼
FastAPI server
  │
  │  8. Streams signed file back to client
  │  9. Deletes both temp files
  │
  ▼
Client  (receives signed binary)
```

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Linux host** | Ubuntu 22.04 / Debian 12 or later recommended |
| **Docker + Docker Compose** | v2.x (`docker compose`, not `docker-compose`) |
| **Azure Key Vault** | With a code-signing certificate (RSA 2048+ or EC P-256+) |
| **Azure credentials** | Service principal **or** managed identity |

> **Note:** For bare-metal installs (no Docker) you additionally need .NET 8 SDK and Python 3.12+.

---

## Azure setup

Complete this section before deploying the server.

### 1. Create an Azure App Registration (service principal)

Skip this step if you are running on an Azure VM/AKS and will use managed identity.

```bash
az ad app create --display-name "SignerServer"
# Note the appId (CLIENT_ID) from the output

az ad sp create --id <appId>

az ad app credential reset --id <appId> --years 2
# Note the password (CLIENT_SECRET) from the output
```

### 2. Create or import a code-signing certificate

**Option A — self-signed (for testing only):**
```bash
az keyvault certificate create \
  --vault-name <your-vault-name> \
  --name <cert-name> \
  --policy "$(az keyvault certificate get-default-policy)"
```

**Option B — import a real OV/EV certificate from a CA (production):**
```bash
# Convert your PFX to PEM first if needed:
openssl pkcs12 -in certificate.pfx -out certificate.pem -nodes

az keyvault certificate import \
  --vault-name <your-vault-name> \
  --name <cert-name> \
  --file certificate.pem
```

### 3. Grant the service principal access to Key Vault

Using Azure RBAC (recommended — requires Key Vault to have RBAC enabled):

```bash
KV_ID=$(az keyvault show --name <your-vault-name> --query id -o tsv)

# Read the certificate (public portion)
az role assignment create \
  --role "Key Vault Certificate User" \
  --assignee <CLIENT_ID> \
  --scope "$KV_ID"

# Use the key to sign hashes
az role assignment create \
  --role "Key Vault Crypto User" \
  --assignee <CLIENT_ID> \
  --scope "$KV_ID"
```

Using legacy access policies (if RBAC is not enabled):

```bash
az keyvault set-policy \
  --name <your-vault-name> \
  --spn <CLIENT_ID> \
  --certificate-permissions get list \
  --key-permissions sign get
```

### 4. Note your values

You will need these for the `.env` file:

| Value | Where to find it |
|---|---|
| `KEY_VAULT_URL` | Azure Portal → Key Vault → Overview → Vault URI |
| `CERTIFICATE_NAME` | Azure Portal → Key Vault → Certificates → name |
| `TENANT_ID` | Azure Portal → Azure Active Directory → Overview → Tenant ID |
| `CLIENT_ID` | Azure Portal → App Registrations → your app → Application (client) ID |
| `CLIENT_SECRET` | Output from `az ad app credential reset` above |

---

## Deployment — Docker with systemd (recommended)

This is the recommended production setup. The container starts automatically on boot and restarts on failure.

### Step 1 — Install Docker

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Enable Docker at boot
sudo systemctl enable docker
sudo systemctl start docker
```

### Step 2 — Copy the project to the server

```bash
sudo mkdir -p /opt/signer-server
sudo cp -r . /opt/signer-server/
cd /opt/signer-server
```

### Step 3 — Configure the environment

```bash
sudo cp .env.example .env
sudo nano .env      # or: sudo vim .env
```

Fill in at minimum:

```ini
KEY_VAULT_URL=https://your-vault-name.vault.azure.net/
CERTIFICATE_NAME=your-cert-name
TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
CLIENT_SECRET=your-client-secret
API_KEY=replace-with-a-long-random-string
```

Protect the file so only root can read it:

```bash
sudo chmod 600 /opt/signer-server/.env
```

### Step 4 — Build the Docker image

```bash
cd /opt/signer-server
sudo docker compose build
```

This takes a few minutes the first time (downloads .NET SDK and Python layers).

### Step 5 — Install and enable the systemd service

```bash
sudo cp /opt/signer-server/signer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signer
sudo systemctl start signer
```

### Step 6 — Verify it is running

```bash
# Check systemd service status
sudo systemctl status signer

# Check the container is up
sudo docker compose -f /opt/signer-server/docker-compose.yml ps

# Hit the health endpoint
curl http://localhost:8080/health
```

Expected health response:
```json
{
  "status": "ok",
  "key_vault_url": "https://your-vault-name.vault.azure.net/",
  "certificate_name": "your-cert-name",
  "azure_sign_tool_version": "5.0.0"
}
```

### Managing the service

```bash
# Stop
sudo systemctl stop signer

# Restart (e.g. after editing .env)
sudo systemctl restart signer

# View logs
sudo journalctl -u signer -f

# View container logs
sudo docker compose -f /opt/signer-server/docker-compose.yml logs -f
```

---

## Deployment — bare metal

Use this approach if you cannot run Docker.

### Step 1 — Install dependencies

```bash
# Install .NET SDK 8 and AzureSignTool
sudo bash /opt/signer-server/scripts/install_azuresigntool.sh

# Install Python 3.12
sudo apt-get install -y python3.12 python3.12-venv

# Create a virtual environment and install packages
python3.12 -m venv /opt/signer-server/venv
source /opt/signer-server/venv/bin/activate
pip install -r /opt/signer-server/requirements.txt
```

### Step 2 — Configure

```bash
cp /opt/signer-server/.env.example /opt/signer-server/.env
nano /opt/signer-server/.env
chmod 600 /opt/signer-server/.env
```

### Step 3 — Create a systemd service (bare metal)

```bash
sudo tee /etc/systemd/system/signer.service > /dev/null <<'EOF'
[Unit]
Description=Windows Binary Signing Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=signer
WorkingDirectory=/opt/signer-server
EnvironmentFile=/opt/signer-server/.env
ExecStart=/opt/signer-server/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create a dedicated non-root user
sudo useradd -r -s /bin/false signer
sudo chown -R signer:signer /opt/signer-server

sudo systemctl daemon-reload
sudo systemctl enable signer
sudo systemctl start signer
```

---

## Configuration reference

All settings are read from environment variables or a `.env` file in the working directory.

| Variable | Required | Default | Description |
|---|---|---|---|
| `KEY_VAULT_URL` | **Yes** | — | Full URL: `https://<vault>.vault.azure.net/` |
| `CERTIFICATE_NAME` | **Yes** | — | Name of certificate stored in Key Vault |
| `TENANT_ID` | No | — | Azure AD tenant ID (service principal auth) |
| `CLIENT_ID` | No | — | App/service principal client ID |
| `CLIENT_SECRET` | No | — | App/service principal secret |
| `API_KEY` | No | *(disabled)* | If set, clients must send `X-API-Key: <value>` |
| `DEFAULT_TIMESTAMP_URL` | No | DigiCert | RFC-3161 timestamp server URL |
| `DEFAULT_TIMESTAMP_DIGEST` | No | `sha256` | Digest for timestamp: `sha256`, `sha384`, `sha512` |
| `MAX_UPLOAD_BYTES` | No | `209715200` | Maximum upload size (200 MB) |
| `AZURE_SIGN_TOOL_PATH` | No | `AzureSignTool` | Full path to binary if not on `PATH` |

**Authentication priority:** If `CLIENT_SECRET` is set, client credentials are used. Otherwise AzureSignTool falls back to managed identity, then environment credentials, then Azure CLI — in that order.

---

## Putting it behind TLS with nginx

Never expose the signing server directly on the internet without TLS. Here is a minimal nginx config using Let's Encrypt.

### Install nginx and Certbot

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

### Create the nginx site

```bash
sudo tee /etc/nginx/sites-available/signer > /dev/null <<'EOF'
server {
    listen 80;
    server_name signer.example.com;

    # Certbot will add the TLS block automatically
    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Allow large binary uploads (match MAX_UPLOAD_BYTES)
        client_max_body_size 200M;
        proxy_read_timeout   300s;
        proxy_send_timeout   300s;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/signer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Obtain a TLS certificate

```bash
sudo certbot --nginx -d signer.example.com
```

Certbot will automatically configure HTTPS and set up auto-renewal. Your signing endpoint is now available at `https://signer.example.com/sign`.

---

## API reference

Interactive Swagger UI: `http://localhost:8080/docs`
OpenAPI schema: `http://localhost:8080/openapi.json`

---

### `GET /health`

No authentication required. Returns server status and AzureSignTool version.

**Response**
```json
{
  "status": "ok",
  "key_vault_url": "https://my-vault.vault.azure.net/",
  "certificate_name": "my-cert",
  "azure_sign_tool_version": "5.0.0"
}
```

If `azure_sign_tool_version` is `null`, AzureSignTool is not on PATH and signing will fail.

---

### `POST /sign`

Sign a PE binary. Returns the signed file as a download.

**Request headers**

| Header | Required | Description |
|---|---|---|
| `X-API-Key` | If configured | Shared secret set in `API_KEY` |
| `Content-Type` | Yes | `multipart/form-data` |

**Form body**

| Field | Type | Description |
|---|---|---|
| `file` | file | The PE binary to sign (.exe, .dll, .msi, .cab, .appx, …) |

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `description` | string | — | Text shown in the Windows security dialog (e.g. your product name) |
| `description_url` | string | — | URL shown in the Windows security dialog |
| `timestamp_url` | string | Server default | RFC-3161 timestamp server |
| `timestamp_digest` | string | `sha256` | Digest algorithm for the timestamp: `sha256`, `sha384`, `sha512` |
| `certificate_name` | string | Server default | Override the Key Vault certificate for this request |
| `append` | boolean | `false` | Append the signature instead of replacing an existing one |

**Response**

On success: `200 OK` with `Content-Type: application/octet-stream` — the signed binary as a file download.

On error: JSON body with a `detail` field explaining the failure.

---

## Client usage examples

### curl

```bash
# Basic signing
curl -X POST https://signer.example.com/sign \
  -H "X-API-Key: your-api-key" \
  -F "file=@MyApp.exe" \
  --output MyApp-signed.exe

# With description and custom timestamp server
curl -X POST https://signer.example.com/sign \
  -H "X-API-Key: your-api-key" \
  -F "file=@MyApp.exe" \
  -G \
  --data-urlencode "description=My Application v2.1" \
  --data-urlencode "description_url=https://example.com" \
  --data-urlencode "timestamp_url=http://timestamp.sectigo.com" \
  --output MyApp-signed.exe
```

### Python

```python
import requests

SERVER = "https://signer.example.com"
API_KEY = "your-api-key"

def sign_binary(input_path: str, output_path: str, description: str = None):
    with open(input_path, "rb") as f:
        resp = requests.post(
            f"{SERVER}/sign",
            headers={"X-API-Key": API_KEY},
            files={"file": (input_path, f, "application/octet-stream")},
            params={"description": description} if description else {},
            timeout=120,
        )
    resp.raise_for_status()
    with open(output_path, "wb") as out:
        out.write(resp.content)
    print(f"Signed: {output_path}")

sign_binary("MyApp.exe", "MyApp-signed.exe", description="My Application")
sign_binary("Setup.msi", "Setup-signed.msi", description="My Installer")
```

### PowerShell (from Windows build agent)

```powershell
$server  = "https://signer.example.com"
$apiKey  = "your-api-key"
$input   = "MyApp.exe"
$output  = "MyApp-signed.exe"

$form = @{ file = Get-Item $input }
Invoke-RestMethod `
    -Uri "$server/sign?description=My+Application" `
    -Method Post `
    -Headers @{ "X-API-Key" = $apiKey } `
    -Form $form `
    -OutFile $output

Write-Host "Signed file saved to $output"
```

### GitHub Actions

```yaml
- name: Sign binary
  run: |
    curl -fsSL -X POST "${{ secrets.SIGNER_URL }}/sign" \
      -H "X-API-Key: ${{ secrets.SIGNER_API_KEY }}" \
      -F "file=@dist/MyApp.exe" \
      -G --data-urlencode "description=My Application ${{ github.ref_name }}" \
      --output dist/MyApp-signed.exe
```

---

## Verifying a signature

### On Windows

Right-click the file → Properties → Digital Signatures tab.

Or from PowerShell:
```powershell
Get-AuthenticodeSignature .\MyApp-signed.exe | Format-List
```

### On Linux

```bash
# Install osslsigncode
sudo apt-get install -y osslsigncode

osslsigncode verify -in MyApp-signed.exe
```

---

## Troubleshooting

### `azure_sign_tool_version` is null in /health

AzureSignTool is not found on `PATH`.

- **Docker:** Rebuild the image — `sudo docker compose build --no-cache`
- **Bare metal:** Re-run `scripts/install_azuresigntool.sh` and ensure `~/.dotnet/tools` is in `PATH`

### `Signing failed: ... Unauthorized`

The service principal does not have permission to use the Key Vault key.

1. Verify the `CLIENT_ID`, `CLIENT_SECRET`, and `TENANT_ID` values in `.env`.
2. Re-check the role assignments in [Azure setup step 3](#3-grant-the-service-principal-access-to-key-vault).
3. Wait 1–2 minutes after assigning roles — Azure RBAC propagation can be slow.

### `Signing failed: ... certificate not found`

The `CERTIFICATE_NAME` does not match any certificate in the vault.

```bash
# List available certificates
az keyvault certificate list --vault-name <vault-name> --query "[].name" -o tsv
```

### Container exits immediately after `docker compose up`

Check the logs:
```bash
sudo docker compose logs signer
```

The most common cause is a missing or invalid `.env` file. Ensure all required variables are set.

### `413 Request Entity Too Large`

The binary exceeds `MAX_UPLOAD_BYTES` (default 200 MB). Increase it in `.env` and also update `client_max_body_size` in the nginx config if you are using a reverse proxy.

### Signing succeeds but Windows still shows "Unknown publisher"

This is expected with a self-signed or OV certificate on a fresh machine. Windows SmartScreen reputation is built up over time. For EV certificates, the warning is suppressed immediately.

---

## Security notes

- **Always set `API_KEY`** — without it the signing endpoint is unauthenticated.
- **Always run behind TLS** — use the nginx config above or another reverse proxy.
- **Prefer managed identity** over client secrets when running on Azure — no credentials to rotate or leak.
- **The private key never leaves Azure Key Vault** — AzureSignTool only sends the file hash.
- **Temp files** are written to `/tmp` and deleted immediately after signing, regardless of success or failure.
- **Restrict network access** — expose port 8080 only to localhost and let nginx handle external traffic.
- **Rotate `API_KEY`** periodically and treat it like a password.
