from pydantic import BaseModel
from typing import Optional


class SigningOptions(BaseModel):
    description: Optional[str] = None
    description_url: Optional[str] = None
    timestamp_url: Optional[str] = None
    timestamp_digest: Optional[str] = None  # sha256 | sha384 | sha512
    certificate_name: Optional[str] = None  # Override default cert from config
    append_signature: bool = False  # Append rather than replace existing signature


class HealthResponse(BaseModel):
    status: str
    key_vault_url: str
    certificate_name: str
    azure_sign_tool_version: Optional[str] = None


class SignResponse(BaseModel):
    filename: str
    original_size: int
    signed_size: int
    message: str
