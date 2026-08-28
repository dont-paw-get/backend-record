"""문장/책 표지 이미지 OCR API.

Frontend에서 Crop/회전까지 완료된 최종 책 문장/표지 이미지를 업로드받아
AWS Bedrock Qwen3-VL로 텍스트를 추출한 뒤, 사용하기 쉬운 형태로 반환한다.
Bedrock 관련 세부 구현은 app.services.bedrock_ocr 안에 격리되어 있으며
이 라우터는 파일 검증과 에러 매핑만 담당한다.

CLIAR-143: OCR Provider를 AWS Bedrock Qwen3-VL로 완전히 전환했다. 이
모듈은 더 이상 NAVER CLOVA OCR을 호출하지 않는다.
"""
from fastapi import APIRouter, HTTPException, Query, UploadFile, status

from app.schemas.ocr import OcrCoverResponse, OcrSentencesResponse
from app.services import bedrock_ocr
from app.services.bedrock_ocr import (
    BedrockOcrEmptyResultError,
    BedrockOcrRequestFailedError,
    BedrockOcrTimeoutError,
)

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
    model_id: str | None = Query(
        default=None,
        description="사용할 Bedrock 모델 ID (예: 'qwen.qwen3-vl-235b-a22b'). 미지정 시 설정값(BEDROCK_OCR_MODEL_ID) 사용",
    ),
) -> OcrSentencesResponse:
    """책 문장 이미지를 업로드받아 OCR 텍스트를 추출한다."""
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

    return OcrSentencesResponse(
        text=result.text,
        lines=result.lines,
        request_id=result.request_id,
        confidence=result.confidence,
        language=result.language,
        provider="bedrock",
    )


@router.post("/covers", response_model=OcrCoverResponse)
async def create_ocr_cover(
    image: UploadFile,
    model_id: str | None = Query(
        default=None,
        description="사용할 Bedrock 모델 ID (예: 'qwen.qwen3-vl-235b-a22b'). 미지정 시 설정값(BEDROCK_OCR_MODEL_ID) 사용",
    ),
) -> OcrCoverResponse:
    """책 표지 이미지를 업로드받아 제목/저자 후보를 추출한다.

    OCR 결과만으로는 제목/저자를 확정할 수 없으므로 응답은 "후보"이며,
    실제 도서 등록/검색/저장은 이 API의 책임이 아니다.
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
