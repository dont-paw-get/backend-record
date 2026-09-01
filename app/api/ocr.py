"""
문장/책 표지 이미지 OCR API
"""
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status

from app.core.config import settings
from app.providers.auth_provider import get_access_token, get_current_member_id
from app.providers.book_provider import (
    BookProviderError,
    InvalidIsbnError,
    create_scrap,
    register_library_book,
    search_book_by_isbn,
)
from app.schemas.ocr import OcrCoverResponse, OcrSentencesResponse
from app.services import bedrock_ocr, s3_upload
from app.services.bedrock_ocr import (
    BedrockOcrEmptyResultError,
    BedrockOcrRequestFailedError,
    BedrockOcrTimeoutError,
)
from app.services.s3_upload import S3UploadError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])

MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024  # 최대 이미지 크기: 50MB

# content type -> 이미지 포맷
SUPPORTED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
}


@router.post("/sentences", response_model=OcrSentencesResponse)
async def create_ocr_sentences(
    image: UploadFile,
    member_id: Annotated[Any, Depends(get_current_member_id)],
    access_token: Annotated[str, Depends(get_access_token)],
    book_id: Annotated[
        int,
        Form(description="스크랩을 연결할 backend-book 서재 도서의 ID"),
    ],
    page_number: Annotated[
        int | None,
        Form(description="스크랩한 문장이 위치한 페이지 번호 (선택)"),
    ] = None,
    memo: Annotated[
        str | None,
        Form(description="스크랩에 남길 사용자 메모 (선택)"),
    ] = None,
    scrap_image_url: Annotated[
        str | None,
        Form(
            description=(
                "(더 이상 사용되지 않음, 하위 호환을 위해 요청 필드만 유지) "
                "RECORD-2부터 실제 스크랩 이미지 URL은 OCR에 사용한 원본 이미지를 "
                "S3/CloudFront에 저장해 서버가 직접 생성한다."
            )
        ),
    ] = None,
    provider: Literal["clova", "bedrock"] | None = Query(
        default=None,
        description="OCR 엔진 선택 ('clova' 또는 'bedrock'). 미지정 시 설정된 기본값(OCR_PROVIDER) 사용",
    ),
    model_id: str | None = Query(
        default=None,
        description="사용할 Bedrock 모델 ID (예: 'qwen.qwen3-vl-235b-a22b'). 미지정 시 설정값(BEDROCK_OCR_MODEL_ID) 사용",
    ),
    save_scrap: bool = Query(
        default=True,
        description=(
            "RECORD-3A: true(기본값)면 기존과 동일하게 OCR 후 backend-book에 "
            "스크랩을 자동 저장하고 scrap_id를 반환한다. false면 OCR과 S3 이미지 "
            "저장만 수행하고(backend-book 저장은 호출하지 않음) scrap_id=null을 "
            "반환한다 - 사용자가 확인/수정 후 별도로 스크랩 저장 API를 호출하는 "
            "흐름을 위한 OCR-only 모드."
        ),
    ),
) -> OcrSentencesResponse:
    """
    책 문장 이미지를 업로드받아 OCR 텍스트를 추출한다.

    save_scrap=true(기본값)이면 인식한 문장을 backend-book 서재 도서(book_id)의
    스크랩으로 자동 등록한다(기존 동작, 하위 호환). save_scrap=false이면 OCR과
    S3 이미지 저장까지만 수행하고 backend-book 저장은 호출하지 않는다.
    """
    image_format = _validate_content_type(image.content_type)
    image_bytes = await image.read()
    _validate_image_bytes(image_bytes)

    try:
        result = await bedrock_ocr.extract_text_from_image(
            image_bytes, image_format, model_id=model_id
        )
    except BedrockOcrTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OCR 요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.",
        )
    except BedrockOcrRequestFailedError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR 서비스 처리 중 오류가 발생했습니다.",
        )
    except BedrockOcrEmptyResultError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="이미지에서 인식된 텍스트가 없습니다.",
        )

    # RECORD-2: OCR이 성공한 이미지만 S3에 저장한다. 여기서 실패하면 backend-book에
    # 잘못되거나 없는 이미지 URL로 스크랩을 생성하지 않도록 create_scrap을 호출하지
    # 않고 즉시 오류로 응답한다. 요청에 scrap_image_url이 별도로 실려 와도, 이번
    # 스크랩의 실제 원본 이미지를 저장한 이 URL로 대체한다.
    try:
        object_key = await s3_upload.upload_scrap_image(
            image_bytes, image.content_type
        )
    except S3UploadError as exc:
        logger.warning("scrap image S3 upload failed (book_id=%s): %s", book_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="스크랩 이미지 저장 처리 중 오류가 발생했습니다.",
        )

    generated_scrap_image_url = s3_upload.build_cloudfront_url(object_key)

    # RECORD-3A: save_scrap=false는 OCR-only 모드로, backend-book 저장을 전혀
    # 호출하지 않는다. 원본 이미지는 두 모드 모두 위에서 이미 S3에 저장했으므로,
    # 이후 사용자가 확인/수정 후 별도로 스크랩 저장 API를 호출할 때
    # 이 generated_scrap_image_url을 그대로 사용할 수 있다.
    scrap_id = None
    if save_scrap:
        try:
            scrap_id = await create_scrap(
                access_token,
                book_id,
                sentence=result.text,
                page_number=page_number,
                scrap_image_url=generated_scrap_image_url,
                memo=memo,
            )
        except BookProviderError as exc:
            logger.warning("create_scrap failed (book_id=%s): %s", book_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="문장 스크랩 저장 처리 중 오류가 발생했습니다.",
            )

    return OcrSentencesResponse(
        text=result.text,
        lines=result.lines,
        request_id=result.request_id,
        confidence=result.confidence,
        language=result.language,
        provider="bedrock",
        book_id=book_id,
        scrap_id=scrap_id,
        scrap_image_url=generated_scrap_image_url,
    )


@router.post("/covers", response_model=OcrCoverResponse)
async def create_ocr_cover(
    image: UploadFile,
    member_id: Annotated[Any, Depends(get_current_member_id)],
    access_token: Annotated[str, Depends(get_access_token)],
    model_id: str | None = Query(
        default=None,
        description="사용할 Bedrock 모델 ID (예: 'qwen.qwen3-vl-235b-a22b'). 미지정 시 설정값(BEDROCK_OCR_MODEL_ID) 사용",
    ),
) -> OcrCoverResponse:
    """
    책 표지 이미지를 업로드받아 제목/저자/ISBN 후보를 추출하고, 사용자의
    개인 서재(backend-book)에 책을 등록한다.
    """
    image_format = _validate_content_type(image.content_type)
    image_bytes = await image.read()
    _validate_image_bytes(image_bytes)

    try:
        result = await bedrock_ocr.extract_book_cover_candidates(
            image_bytes, image_format, model_id=model_id
        )
    except BedrockOcrTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OCR 요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.",
        )
    except BedrockOcrRequestFailedError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR 서비스 처리 중 오류가 발생했습니다.",
        )
    except BedrockOcrEmptyResultError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="이미지에서 인식된 텍스트가 없습니다.",
        )

    isbn = result.isbn
    search = None
    if isbn:
        try:
            search = await search_book_by_isbn(access_token, isbn)
        except InvalidIsbnError:
            search = None
        except BookProviderError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="도서 정보 조회 중 오류가 발생했습니다.",
            )

    already_registered = search is not None and search.library_book is not None
    searched_book = search.library_book if already_registered else (
        search.book if search is not None else None
    )

    if already_registered:
        book_id = searched_book.get("bookId")
    else:
        if searched_book is not None:
            title = searched_book.get("title") or result.title_candidate
            author = searched_book.get("author")
            isbn = searched_book.get("isbn") or isbn
            publisher = searched_book.get("publisher")
            published_date = searched_book.get("publishedDate")
            total_pages = searched_book.get("totalPages")
            cover_url = searched_book.get("coverUrl")
        else:
            # 어디에서도 도서 정보를 찾지 못한 경우 OCR 후보로 폴백 등록한다.
            title = result.title_candidate
            author = result.author_candidates[0] if result.author_candidates else None
            publisher = None
            published_date = None
            total_pages = None
            cover_url = None
        try:
            book_id = await register_library_book(
                access_token,
                title=title,
                author=author,
                isbn=isbn,
                publisher=publisher,
                published_date=published_date,
                total_pages=total_pages,
                cover_url=cover_url,
            )
        except BookProviderError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="서재 책 등록 처리 중 오류가 발생했습니다.",
            )

    return OcrCoverResponse(
        title_candidate=result.title_candidate,
        author_candidates=result.author_candidates,
        lines=result.lines,
        request_id=result.request_id,
        confidence=result.confidence,
        isbn=isbn,
        book_id=book_id,
        already_registered=already_registered,
        book=searched_book,
    )


def _validate_content_type(content_type: str | None) -> str:
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="지원하지 않는 이미지 형식입니다. image/jpeg 또는 image/png만 허용됩니다.",
        )
    return SUPPORTED_CONTENT_TYPES[content_type]


def _validate_image_bytes(image_bytes: bytes) -> None:
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미지 파일이 비어 있습니다.",
        )

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="이미지 파일 크기가 50MB를 초과했습니다.",
        )
