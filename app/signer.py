import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from azure.identity import ClientSecretCredential, DefaultAzureCredential

from .config import settings

logger = logging.getLogger(__name__)

_KEYVAULT_SCOPE = "https://vault.azure.net/.default"

# Module-level credential — azure-identity caches and auto-refreshes tokens
_credential = None


def _get_credential():
    global _credential
    if _credential is None:
        if settings.tenant_id and settings.client_id and settings.client_secret:
            _credential = ClientSecretCredential(
                tenant_id=settings.tenant_id,
                client_id=settings.client_id,
                client_secret=settings.client_secret,
            )
        else:
            _credential = DefaultAzureCredential()
    return _credential


def _fetch_token() -> str:
    """Fetch a bearer token for Azure Key Vault (blocking, run in executor)."""
    token = _get_credential().get_token(_KEYVAULT_SCOPE)
    return token.token


async def _get_token_async() -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_token)


async def get_tool_version() -> str | None:
    """Return jsign version string, or None if java/jar not found."""
    if not os.path.exists(settings.jsign_path):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "java", "-jar", settings.jsign_path, "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        first_line = output.splitlines()[0] if output.splitlines() else ""
        return first_line.strip() or "jsign (available)"
    except FileNotFoundError:
        return None


async def sign_binary(
    input_path: str,
    certificate_name: str,
    description: str | None = None,
    description_url: str | None = None,
    timestamp_url: str | None = None,
    timestamp_digest: str | None = None,
    append_signature: bool = False,
) -> str:
    """
    Sign a PE binary using jsign backed by Azure Key Vault.

    Fetches a short-lived bearer token from Azure AD, passes it to jsign,
    copies input to a temp file, signs in-place, returns the signed path.
    Caller is responsible for cleanup.
    """
    suffix = Path(input_path).suffix or ".exe"
    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_out.close()
    output_path = tmp_out.name

    shutil.copy2(input_path, output_path)

    token = await _get_token_async()

    cmd = _build_command(
        output_path=output_path,
        certificate_name=certificate_name,
        token=token,
        description=description,
        description_url=description_url,
        timestamp_url=timestamp_url,
        timestamp_digest=timestamp_digest,
    )

    logger.info("Running: %s", " ".join(_redact(cmd)))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        os.unlink(output_path)
        raise RuntimeError(
            f"jsign exited {proc.returncode}:\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )

    logger.info("Signing succeeded: %s", stdout.decode().strip())
    return output_path


def _normalise_digest(digest: str | None) -> str:
    d = (digest or settings.default_digest).upper().replace("SHA", "SHA-").replace("SHA--", "SHA-")
    return d if d in ("SHA-256", "SHA-384", "SHA-512") else "SHA-256"


def _build_command(
    output_path: str,
    certificate_name: str,
    token: str,
    description: str | None,
    description_url: str | None,
    timestamp_url: str | None,
    timestamp_digest: str | None,
) -> list[str]:
    cmd: list[str] = [
        "java", "-jar", settings.jsign_path,
        "--storetype", "AZUREKEYVAULT",
        "--keystore", settings.key_vault_url,
        "--alias", certificate_name,
        "--storepass", token,
        "--alg", _normalise_digest(timestamp_digest),
    ]

    ts_url = timestamp_url or settings.default_timestamp_url
    if ts_url:
        cmd += ["--tsaurl", ts_url, "--tsmode", "RFC3161"]

    if description:
        cmd += ["--name", description]
    if description_url:
        cmd += ["--url", description_url]

    cmd.append(output_path)
    return cmd


def _redact(cmd: list[str]) -> list[str]:
    """Replace the bearer token after --storepass with ***."""
    redacted = list(cmd)
    for i, token in enumerate(redacted):
        if token == "--storepass" and i + 1 < len(redacted):
            redacted[i + 1] = "***"
    return redacted
