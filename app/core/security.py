import hashlib
import logging
import secrets

from fastapi import Header, HTTPException, Request, status

logger = logging.getLogger("uvicorn.error")


def api_key_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _extract_token(
    authorization: str | None,
    x_api_key: str | None,
) -> tuple[str | None, str, str | None]:
    if x_api_key:
        return x_api_key.strip(), "x-api-key", None
    if not authorization:
        return None, "missing", None
    value = authorization.strip()
    scheme, separator, credential = value.partition(" ")
    if separator and scheme.casefold() == "bearer":
        return credential.strip(), "authorization", scheme
    return value, "authorization", scheme or None


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings = request.app.state.settings
    if not settings.require_api_key:
        logger.info(
            "API auth bypassed: require_api_key=false path=%s",
            request.url.path,
        )
        return

    token, token_source, authorization_scheme = _extract_token(authorization, x_api_key)
    matched = bool(token) and secrets.compare_digest(token, settings.api_key)
    forwarded_proto = request.headers.get("x-forwarded-proto")
    client_host = request.client.host if request.client else "unknown"
    log_values = {
        "path": request.url.path,
        "client": client_host,
        "direct_scheme": request.url.scheme,
        "forwarded_proto": forwarded_proto or "missing",
        "authorization_present": authorization is not None,
        "authorization_scheme": authorization_scheme or "missing",
        "bearer": bool(authorization_scheme and authorization_scheme.casefold() == "bearer"),
        "x_api_key_present": x_api_key is not None,
        "token_source": token_source,
        "configured_key_loaded": bool(settings.api_key),
        "configured_key_is_default": settings.api_key == "change-me",
        "configured_key_length": len(settings.api_key),
        "configured_key": settings.api_key,
        "configured_key_fingerprint": api_key_fingerprint(settings.api_key),
        "credential_length": len(token) if token else 0,
        "credential": token or "missing",
        "credential_fingerprint": api_key_fingerprint(token) if token else "missing",
        "matched": matched,
    }

    log_message = (
        "API auth diagnostic: path=%(path)s client=%(client)s "
        "direct_scheme=%(direct_scheme)s forwarded_proto=%(forwarded_proto)s "
        "authorization_present=%(authorization_present)s "
        "authorization_scheme=%(authorization_scheme)s bearer=%(bearer)s "
        "x_api_key_present=%(x_api_key_present)s token_source=%(token_source)s "
        "configured_key_loaded=%(configured_key_loaded)s "
        "configured_key_is_default=%(configured_key_is_default)s "
        "configured_key_length=%(configured_key_length)s "
        "configured_key=%(configured_key)s "
        "configured_key_fingerprint=%(configured_key_fingerprint)s "
        "credential_length=%(credential_length)s "
        "credential=%(credential)s "
        "credential_fingerprint=%(credential_fingerprint)s matched=%(matched)s"
    )
    if matched:
        logger.info(log_message, log_values)
    else:
        logger.warning(log_message, log_values)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
