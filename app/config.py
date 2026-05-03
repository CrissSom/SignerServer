from pydantic_settings import BaseSettings
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
    default_timestamp_digest: str = "sha256"

    # Path to AzureSignTool binary (defaults to 'AzureSignTool' on PATH)
    azure_sign_tool_path: str = "AzureSignTool"

    # Maximum upload size in bytes (default 200 MB)
    max_upload_bytes: int = 200 * 1024 * 1024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
