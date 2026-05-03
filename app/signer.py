import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


async def get_tool_version() -> str | None:
    """Return AzureSignTool version string, or None if not found."""
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.azure_sign_tool_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if proc.returncode == 0 else None
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
    Sign a PE binary using AzureSignTool backed by Azure Key Vault.

    Copies the input file to a temp output path, signs it in-place, and
    returns the path to the signed file.  Caller is responsible for cleanup.
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
        append_signature=append_signature,
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
            f"AzureSignTool exited {proc.returncode}:\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )

    logger.info("Signing succeeded: %s", stdout.decode().strip())
    return output_path


def _build_command(
    output_path: str,
    certificate_name: str,
    description: str | None,
    description_url: str | None,
    timestamp_url: str | None,
    timestamp_digest: str | None,
    append_signature: bool,
) -> list[str]:
    cmd: list[str] = [
        settings.azure_sign_tool_path, "sign",
        "--azure-key-vault-url", settings.key_vault_url,
        "--azure-key-vault-certificate", certificate_name,
    ]

    # Auth: prefer explicit client credentials, else AzureSignTool will try
    # managed identity / environment / Azure CLI automatically.
    if settings.tenant_id:
        cmd += ["--azure-key-vault-tenant-id", settings.tenant_id]
    if settings.client_id:
        cmd += ["--azure-key-vault-client-id", settings.client_id]
    if settings.client_secret:
        cmd += ["--azure-key-vault-client-secret", settings.client_secret]

    # Managed identity flag — only added when no client secret is configured
    if not settings.client_secret:
        cmd += ["--azure-key-vault-managed-identity"]

    # Timestamp
    ts_url = timestamp_url or settings.default_timestamp_url
    ts_digest = timestamp_digest or settings.default_timestamp_digest
    if ts_url:
        cmd += ["--timestamp-rfc3161", ts_url, "--timestamp-digest", ts_digest]

    if description:
        cmd += ["--description", description]
    if description_url:
        cmd += ["--description-url", description_url]
    if append_signature:
        cmd.append("--append-signature")

    cmd.append(output_path)
    return cmd


def _redact(cmd: list[str]) -> list[str]:
    """Replace secret values in logged command with ***."""
    redacted = list(cmd)
    secret_flags = {"--azure-key-vault-client-secret"}
    for i, token in enumerate(redacted):
        if token in secret_flags and i + 1 < len(redacted):
            redacted[i + 1] = "***"
    return redacted
