import logging
import os
import tempfile
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Security,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security.api_key import APIKeyHeader

from .config import settings
from .models import HealthResponse
from .signer import get_tool_version, sign_binary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_tool_version: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tool_version
    _tool_version = await get_tool_version()
    if _tool_version:
        logger.info("jsign: %s", _tool_version)
    else:
        logger.warning(
            "jsign not found at %s or Java not available — signing requests will fail.",
            settings.jsign_path,
        )
    yield


app = FastAPI(
    title="Windows Binary Signing Server",
    description=(
        "Signs Windows PE binaries (EXE, DLL, MSI, etc.) using Authenticode "
        "via Azure Key Vault. The private key never leaves Key Vault."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: Optional[str] = Security(_api_key_header)):
    if not settings.api_key:
        return  # Auth disabled — no key configured
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health():
    """Liveness + readiness check."""
    return HealthResponse(
        status="ok",
        key_vault_url=settings.key_vault_url,
        certificate_name=settings.certificate_name,
        azure_sign_tool_version=_tool_version,
    )


@app.post(
    "/sign",
    tags=["signing"],
    summary="Sign a Windows PE binary",
    response_description="The Authenticode-signed binary file",
)
async def sign_file(
    request: Request,
    file: UploadFile = File(..., description="PE binary to sign (.exe, .dll, .msi, …)"),
    description: Optional[str] = Query(None, description="Authenticode description string"),
    description_url: Optional[str] = Query(None, description="URL shown in the signature"),
    timestamp_url: Optional[str] = Query(
        None, description="RFC-3161 timestamp server (default: DigiCert)"
    ),
    timestamp_digest: Optional[str] = Query(
        None, description="Timestamp digest algorithm: sha256 (default), sha384, sha512"
    ),
    certificate_name: Optional[str] = Query(
        None, description="Key Vault certificate name (overrides server default)"
    ),
    append: bool = Query(False, description="Append signature instead of replacing"),
    _auth=Depends(require_api_key),
):
    """
    Upload a Windows PE binary and receive back an Authenticode-signed copy.

    The private key stays in Azure Key Vault at all times — only the file hash
    is sent for signing.
    """
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.max_upload_bytes} bytes.",
        )

    original_filename = file.filename or "unsigned.exe"
    suffix = os.path.splitext(original_filename)[1] or ".exe"

    # Save upload to a temp file
    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp_in)
        tmp_in.close()
        original_size = os.path.getsize(tmp_in.name)

        logger.info(
            "Signing request: file=%s size=%d cert=%s",
            original_filename,
            original_size,
            certificate_name or settings.certificate_name,
        )

        signed_path = await sign_binary(
            input_path=tmp_in.name,
            certificate_name=certificate_name or settings.certificate_name,
            description=description,
            description_url=description_url,
            timestamp_url=timestamp_url,
            timestamp_digest=timestamp_digest,
            append_signature=append,
        )
    except RuntimeError as exc:
        logger.error("Signing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    finally:
        os.unlink(tmp_in.name)

    # Stream the signed file back and schedule temp-file cleanup
    response = FileResponse(
        path=signed_path,
        media_type="application/octet-stream",
        filename=original_filename,
        background=None,
    )

    # Clean up the signed temp file after the response is sent
    async def _cleanup():
        try:
            os.unlink(signed_path)
        except OSError:
            pass

    response.background = _cleanup  # type: ignore[assignment]
    return response
