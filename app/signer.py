import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


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
        # First line is typically "Jsign x.x (https://...)"
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

    Copies the input file to a temp output path, signs it in-place, and
    returns the path to the signed file. Caller is responsible for cleanup.
    """
    suffix = Path(input_path).suffix or ".exe"
    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_out.close()
    output_path = tmp_out.name

    shutil.copy2(input_path, output_path)

    cmd = _build_command(
        output_path=output_path,
        certificate_name=certificate_name,
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


def _build_storepass() -> str | None:
    """
    Build the jsign storepass string for Azure Key Vault.

    Format: tenantId|clientId|clientSecret
    Returns None to use DefaultAzureCredential (managed identity / env vars).
    """
    if settings.tenant_id or settings.client_id or settings.client_secret:
        return f"{settings.tenant_id or ''}|{settings.client_id or ''}|{settings.client_secret or ''}"
    return None


def _normalise_digest(digest: str | None) -> str:
    """Convert sha256/sha384/sha512 → SHA-256/SHA-384/SHA-512 for jsign."""
    d = (digest or settings.default_digest).upper().replace("SHA", "SHA-").replace("SHA--", "SHA-")
    return d if d in ("SHA-256", "SHA-384", "SHA-512") else "SHA-256"


def _build_command(
    output_path: str,
    certificate_name: str,
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
        "--alg", _normalise_digest(timestamp_digest),
    ]

    storepass = _build_storepass()
    if storepass:
        cmd += ["--storepass", storepass]

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
    """Replace the client secret inside --storepass with ***."""
    redacted = list(cmd)
    for i, token in enumerate(redacted):
        if token == "--storepass" and i + 1 < len(redacted):
            parts = redacted[i + 1].split("|")
            if len(parts) == 3:
                parts[2] = "***"
            redacted[i + 1] = "|".join(parts)
    return redacted
