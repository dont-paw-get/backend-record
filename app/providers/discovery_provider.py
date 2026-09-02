from __future__ import annotations
import logging
from typing import Any
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

CLASSIFY_GENRE_PATH = "/api/v1/classify-genre"


_CLASSIFY_TIMEOUT_SECONDS = 15.0


class DiscoveryProviderError(Exception):
    """backend-discovery 연동 중 발생하는 오류의 베이스 예외."""


async def classify_genre_by_isbn(
    isbn: str
) -> str | None:
    """제목/저자/ISBN 을 backend-discovery 로 보내 표준 장르(genre_type)를 분류받는다.
    """
    if not settings.DISCOVERY_API:
        return None
    
    if not isbn:
        return None

    url = f"{settings.DISCOVERY_API.rstrip('/')}{CLASSIFY_GENRE_PATH}"
    body = {
        "isbn": isbn
    }

    try:
        async with httpx.AsyncClient(timeout=_CLASSIFY_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers={}, json=body)
    except httpx.HTTPError as exc:
        logger.warning("backend-discovery classify-genre request failed: %s", exc)
        return None

    if response.status_code != httpx.codes.OK:
        logger.warning(
            "backend-discovery classify-genre returned status %s",
            response.status_code,
        )
        return None

    payload: Any = response.json()
    genre = payload.get("genre") if isinstance(payload, dict) else None
    if not isinstance(genre, str) or not genre:
        logger.warning("backend-discovery classify-genre response missing genre")
        return None
    return genre
