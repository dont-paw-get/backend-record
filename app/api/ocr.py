"""문장 이미지 OCR API.

Frontend에서 Crop/회전까지 완료된 최종 책 문장 이미지를 업로드받아
CLOVA OCR General API로 텍스트를 추출한 뒤, 사용하기 쉬운 형태로
반환한다. CLOVA 관련 세부 구현은 app.services.clova_ocr 안에 격리되어
있으며 이 라우터는 파일 검증과 에러 매핑만 담당한다.
"""
from fastapi import APIRouter, HTTPException, UploadFile, status

from app.schemas.ocr import OcrCoverResponse, OcrSentencesResponse
from app.services.clova_ocr import (
    ClovaOcrEmptyResultError,
    ClovaOcrRecognitionFailedError,
    ClovaOcrRequestFailedError,
    ClovaOcrTimeoutError,
    extract_book_cover_candidates,
    extract_text_from_image,
)

router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])

MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024  # CLOVA OCR 공식 최대 이미지 크기: 50MB

# content type -> CLOVA OCR에 전달할 이미지 포맷
SUPPORTED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
}


@router.post("/sentences", response_model=OcrSentencesResponse)
async def create_ocr_sentences(image: UploadFile) -> OcrSentencesResponse:
    """책 문장 이미지를 업로드받아 OCR 텍스트를 추출한다."""
    image_format = _validate_content_type(image.content_type)
    image_bytes = await image.read()
    _validate_image_bytes(image_bytes)

    try:
        result = await extract_text_from_image(image_bytes, image_format)
    except ClovaOcrTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OCR 요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.",
        )
    except (ClovaOcrRequestFailedError, ClovaOcrRecognitionFailedError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR 서비스 처리 중 오류가 발생했습니다.",
        )
    except ClovaOcrEmptyResultError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="이미지에서 인식된 텍스트가 없습니다.",
        )

    return OcrSentencesResponse(
        text=result.text,
        lines=result.lines,
        request_id=result.request_id,
        confidence=result.confidence,
    )


@router.post("/covers", response_model=OcrCoverResponse)
async def create_ocr_cover(image: UploadFile) -> OcrCoverResponse:
    """책 표지 이미지를 업로드받아 제목/저자 후보를 추출한다.

    OCR 결과만으로는 제목/저자를 확정할 수 없으므로 응답은 "후보"이며,
    실제 도서 등록/검색/저장은 이 API의 책임이 아니다.
    """
    image_format = _validate_content_type(image.content_type)
    image_bytes = await image.read()
    _validate_image_bytes(image_bytes)

    try:
        result = await extract_book_cover_candidates(image_bytes, image_format)
    except ClovaOcrTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OCR 요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.",
        )
    except (ClovaOcrRequestFailedError, ClovaOcrRecognitionFailedError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OCR 서비스 처리 중 오류가 발생했습니다.",
        )
    except ClovaOcrEmptyResultError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="이미지에서 인식된 텍스트가 없습니다.",
        )

    return OcrCoverResponse(
        title_candidate=result.title_candidate,
        author_candidates=result.author_candidates,
        lines=result.lines,
        request_id=result.request_id,
        confidence=result.confidence,
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
