from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

# backend-auth 회원 조회 엔드포인트(Base URL은 settings.AUTH_API).
USER_ME_PATH = "/api/v1/users/me"
_bearer_scheme = HTTPBearer(auto_error=False)


class AuthProviderError(Exception):
    """backend-auth 연동 중 발생하는 오류의 베이스 예외."""


class UnexpectedAuthResponseError(AuthProviderError):
    """backend-auth 응답에서 기대한 필드를 찾지 못한 경우."""


async def fetch_member_id(access_token: str) -> Any:
    """전달받은 access token으로 backend-auth에서 member_id를 조회한다."""
    url = f"{settings.AUTH_API.rstrip('/')}{USER_ME_PATH}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("backend-auth request failed: %s", exc)
        raise AuthProviderError("backend-auth request failed") from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 access token 입니다.",
        )
    if response.status_code != status.HTTP_200_OK:
        logger.warning(
            "backend-auth returned unexpected status %s", response.status_code
        )
        raise AuthProviderError(
            f"backend-auth returned status {response.status_code}"
        )
    payload = response.json()
    member_id = payload.get("member_id") if isinstance(payload, dict) else None

    if member_id is None:
        logger.warning(
            "member_id not found in backend-auth response (keys=%s)",
            list(payload) if isinstance(payload, dict) else type(payload).__name__,
        )
        raise UnexpectedAuthResponseError("member_id not found in auth response")
    return member_id


async def get_current_member_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
) -> Any:
    """Authorization: Bearer <token> 헤더에서 access token을 받아 member_id를 조회하는 의존성."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="access token이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await fetch_member_id(credentials.credentials)
    except AuthProviderError:
         raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="인증 서비스 처리 중 오류가 발생했습니다.",
        )