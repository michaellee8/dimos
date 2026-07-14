# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cognito JWT auth for operators and API key auth for robots.

Operators sign in against the Cognito user pool from the SPA; this module
only *verifies* the resulting RS256 ID tokens against the pool's JWKS.
The app-level identity is the (verified) email claim, so API key ownership,
robot-ID namespacing and session ownership are all keyed by email.
"""

import asyncio
import logging
import time

from config import settings
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwt

log = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-Robot-API-Key", auto_error=False)

ROBOT_API_KEYS: dict[str, str] = {}

# Hourly TTL so a key rotation doesn't need a restart.
_JWKS_TTL_SEC = 3600

_jwks_lock = asyncio.Lock()
_jwks_keys: dict[str, dict] = {}
_jwks_fetched_at = 0.0


async def _fetch_jwks() -> dict[str, dict]:
    url = f"{settings.cognito_issuer}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    return {k["kid"]: k for k in resp.json()["keys"]}


async def _get_jwk(kid: str) -> dict | None:
    global _jwks_fetched_at
    now = time.monotonic()
    if kid in _jwks_keys and now - _jwks_fetched_at < _JWKS_TTL_SEC:
        return _jwks_keys[kid]
    async with _jwks_lock:
        if kid in _jwks_keys and time.monotonic() - _jwks_fetched_at < _JWKS_TTL_SEC:
            return _jwks_keys[kid]
        try:
            _jwks_keys.update(await _fetch_jwks())
            _jwks_fetched_at = time.monotonic()
        except Exception as e:
            log.error("JWKS fetch failed: %s", e)
    return _jwks_keys.get(kid)


async def decode_token(token: str) -> dict:
    """Verify a Cognito ID token and return our app-level claims.

    `sub` in the returned dict is the user's email (everything downstream keys
    on it), not the Cognito subject.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    jwk = await _get_jwk(kid)
    if jwk is None:
        raise HTTPException(status_code=401, detail="Invalid token: unknown key id")

    try:
        claims = jwt.decode(
            token,
            jwk,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            issuer=settings.cognito_issuer,
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    if claims.get("token_use") != "id":
        raise HTTPException(status_code=401, detail="Invalid token: not an ID token")
    email = claims.get("email")
    if not email or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified")

    role = "admin" if "admin" in claims.get("cognito:groups", []) else "operator"
    return {"sub": email, "role": role, "cognito_sub": claims["sub"]}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await decode_token(credentials.credentials)


async def get_robot_id(api_key: str | None = Security(api_key_header)) -> str:
    if api_key:
        if api_key in ROBOT_API_KEYS:
            return ROBOT_API_KEYS[api_key]

        from models.database import async_session

        from services.keys import validate_api_key

        async with async_session() as db:
            key_record = await validate_api_key(db, api_key)
            if key_record:
                if not key_record.robot_id:
                    log.warning(
                        "API key for owner_id=%s has no robot_id; using owner_id as identity",
                        key_record.owner_id,
                    )
                return key_record.robot_id or key_record.owner_id

    raise HTTPException(status_code=401, detail="Invalid robot credentials")


async def get_robot_owner(api_key: str | None = Security(api_key_header)) -> str:
    if api_key:
        if api_key in ROBOT_API_KEYS:
            return ROBOT_API_KEYS[api_key]
        from models.database import async_session

        from services.keys import validate_api_key

        async with async_session() as db:
            key_record = await validate_api_key(db, api_key)
            if key_record:
                return key_record.owner_id

    raise HTTPException(status_code=401, detail="Invalid robot credentials")


async def get_operator_or_robot(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> dict:
    if api_key:
        robot_id = await get_robot_id(api_key)
        return {"sub": robot_id, "role": "robot"}
    if credentials is not None:
        return await decode_token(credentials.credentials)
    raise HTTPException(status_code=401, detail="Not authenticated")


def register_robot_key(api_key: str, robot_id: str) -> None:
    ROBOT_API_KEYS[api_key] = robot_id
