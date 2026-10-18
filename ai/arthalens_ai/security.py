"""Service-to-service authentication for /internal/* routes.

Only backend/ may call the internal API. It sends ``Authorization: Bearer <AI_SERVICE_TOKEN>``.
Production will add mTLS on top (Milestone 11); the token check stays as defence in depth.
"""

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, status
from pydantic import SecretStr

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or missing service token",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_service_token(expected: SecretStr) -> Callable[[str | None], Awaitable[None]]:
    expected_bytes = expected.get_secret_value().encode()

    async def dependency(authorization: str | None = Header(default=None)) -> None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _UNAUTHORIZED
        # Constant-time comparison so response timing doesn't reveal the token prefix.
        if not hmac.compare_digest(token.encode(), expected_bytes):
            raise _UNAUTHORIZED

    return dependency
