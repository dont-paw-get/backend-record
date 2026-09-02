from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any
import httpx
from fastapi import HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)

LIBRARY_BOOKS_PATH = "/api/v1/library/books"
LIBRARY_SCRAPS_PATH = "/api/v1/library/books/{book_id}/scraps"
BOOK_SEARCH_PATH = "/api/v1/books/search"


class BookProviderError(Exception):
    """backend-book 연동 중 발생하는 오류의 베이스 예외."""


class UnexpectedBookResponseError(BookProviderError):
    """backend-book 응답에서 기대한 필드를 찾지 못한 경우."""


class InvalidIsbnError(BookProviderError):
    """isbn이 없거나 ISBN-10/13 형식이 아니어서 backend-book이 400을 반환한 경우."""


@dataclass
class BookSearchResult:
    library_book: dict[str, Any] | None = None
    book: dict[str, Any] | None = None


async def register_library_book(
    access_token: str,
    *,
    title: str | None,
    author: str | None,
    isbn: str | None = None,
    publisher: str | None = None,
    published_date: str | None = None,
    total_pages: int | None = None,
    cover_url: str | None = None,
) -> Any:
    url = f"{settings.BOOK_API.rstrip('/')}{LIBRARY_BOOKS_PATH}"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {
        "title": title,
        "author": author,
        "isbn": isbn,
        "publisher": publisher,
        "publishedDate": published_date,
        "totalPages": total_pages,
        "coverUrl": cover_url,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.warning("backend-book register request failed: %s", exc)
        raise BookProviderError("backend-book request failed") from exc

    payload = response.json()
    book_id = payload.get("bookId") if isinstance(payload, dict) else None

    if book_id is None:
        raise UnexpectedBookResponseError("book_id not found in book response")
    return book_id


async def create_scrap(
    access_token: str,
    book_id: Any,
    *,
    sentence: str,
    page_number: int | None = None,
    scrap_image_url: str | None = None,
    memo: str | None = None,
) -> Any:
    """OCR로 인식한 문장을 backend-book 서재 도서(book_id)에 스크랩으로 등록한다.
    """
    path = LIBRARY_SCRAPS_PATH.format(book_id=book_id)
    url = f"{settings.BOOK_API.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {
        "sentence": sentence,
        "pageNumber": page_number,
        "scrapImageUrl": scrap_image_url,
        "memo": memo,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.warning("backend-book create scrap request failed: %s", exc)
        raise BookProviderError("backend-book request failed") from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="[backend-book/scrap] 유효하지 않은 access token 입니다.",
        )
    if response.status_code not in (status.HTTP_200_OK, status.HTTP_201_CREATED):
        # 응답 본문(response.text)에는 스크랩 문장 등이 echo 될 수 있어 로그에 남기지 않는다.
        logger.warning(
            "backend-book create scrap failed (book_id=%s, status=%s)",
            book_id,
            response.status_code,
        )
        raise BookProviderError(
            f"backend-book returned status {response.status_code}"
        )

    payload = response.json()
    scrap_id = None
    if isinstance(payload, dict):
        scrap_id = payload.get("scrapId") or payload.get("id")

    if scrap_id is None:
        raise UnexpectedBookResponseError("scrap_id not found in scrap response")
    return scrap_id


async def search_book_by_isbn(access_token: str, isbn: str) -> BookSearchResult:

    url = f"{settings.BOOK_API.rstrip('/')}{BOOK_SEARCH_PATH}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"isbn": isbn}
   
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise BookProviderError("backend-book request failed") from exc

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        raise InvalidIsbnError("유효한 isbn이 필요합니다.")
    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="[backend-book/isbn] 유효하지 않은 access token 입니다.",
        )
    if response.status_code != status.HTTP_200_OK:
        raise BookProviderError(
            f"backend-book returned status {response.status_code}"
        )

    payload = response.json()

    return BookSearchResult(
        library_book=payload.get("libraryBook"),
        book=payload.get("book"),
    )
