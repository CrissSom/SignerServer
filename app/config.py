from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # Azure Key Vault
    key_vault_url: str
    certificate_name: str

    # Azure auth - client credentials (optional; falls back to managed identity / Azure CLI)
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    # API authentication
    api_key: Optional[str] = None  # If set, clients must send X-API-Key header

    # Signing defaults
    default_timestamp_url: str = "http://timestamp.digicert.com"
    default_digest: str = "SHA-256"  # SHA-256, SHA-384, SHA-512

    # Path to jsign JAR
    jsign_path: str = "/opt/jsign.jar"

    # jsign has no --version flag, so the image passes its version in here.
    jsign_version: Optional[str] = None

    # Maximum upload size in bytes (default 200 MB)
    max_upload_bytes: int = 200 * 1024 * 1024

    # extra="ignore" matters in containers: the runtime injects vars this model
    # does not declare (PORT, WEB_CONCURRENCY, LOG_LEVEL, ...) and a stray key in
    # a mounted .env would otherwise abort startup.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
