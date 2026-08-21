"""NAVER Cloud CLOVA OCR General API 연동.

CLOVA OCR 전용 요청/응답 처리를 이 모듈 안에 격리한다. 이 모듈 밖(router 등)
에서는 CLOVA의 raw 응답 구조를 알 필요가 없다.

이 서비스는 OCR이 반환한 텍스트를 그대로 조합하는 역할만 수행하며,
문장 의미를 교정하거나 재작성하지 않는다.
"""
import base64
import logging
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# NAVER Cloud CLOVA OCR General API 공식 문서 기준 timeout (초).
CLOVA_OCR_REQUEST_TIMEOUT_SECONDS = 15.0


class ClovaOcrError(Exception):
    """CLOVA OCR 연동 관련 오류의 베이스 클래스."""


class ClovaOcrTimeoutError(ClovaOcrError):
    """CLOVA OCR API 호출이 timeout된 경우."""


class ClovaOcrRequestFailedError(ClovaOcrError):
    """CLOVA OCR API 호출 자체가 실패했거나(HTTP 오류, 네트워크 오류)
    응답 구조가 예상과 다른 경우."""


class ClovaOcrRecognitionFailedError(ClovaOcrError):
    """CLOVA OCR이 요청은 처리했지만 inferResult가 SUCCESS가 아닌 경우."""


class ClovaOcrEmptyResultError(ClovaOcrError):
    """CLOVA OCR이 SUCCESS를 반환했지만 인식된 텍스트가 없는 경우."""


@dataclass(frozen=True)
class ClovaOcrResult:
    """CLOVA OCR 원본 응답을 애플리케이션 레벨로 가공한 결과.

    CLOVA의 raw JSON 구조(images[].fields[] 등)를 이 밖으로 노출하지
    않기 위한 경계 역할을 한다.
    """

    text: str
    lines: list[str]
    request_id: str
    confidence: float | None


def _build_request_body(image_base64: str, image_format: str, request_id: str) -> dict:
    return {
        "version": "V2",
        "requestId": request_id,
        "timestamp": int(time.time() * 1000),
        "lang": "ko",
        "images": [
            {
                "format": image_format,
                "name": "sentence-image",
                "data": image_base64,
            }
        ],
        "enableTableDetection": False,
    }


def _build_lines_and_text(fields: list[dict]) -> tuple[str, list[str]]:
    """CLOVA OCR fields[]를 lineBreak 기준으로 줄 단위 텍스트로 재구성한다.

    같은 줄에 속한 서로 다른 field는 별도의 단어/어절 단위로 인식된 것이므로
    공백 1칸으로 연결하고, lineBreak가 True인 field에서 줄을 마무리한다.
    빈 inferText는 무시하며, NLP/문장 교정은 수행하지 않는다.
    """
    lines: list[str] = []
    current_line_parts: list[str] = []

    for field in fields:
        infer_text = field.get("inferText", "")
        if infer_text:
            current_line_parts.append(infer_text)

        if field.get("lineBreak"):
            lines.append(" ".join(current_line_parts))
            current_line_parts = []

    if current_line_parts:
        lines.append(" ".join(current_line_parts))

    text = "\n".join(lines)
    return text, lines


def _calculate_average_confidence(fields: list[dict]) -> float | None:
    confidences = [
        field["inferConfidence"]
        for field in fields
        if isinstance(field.get("inferConfidence"), (int, float))
    ]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)


def _parse_clova_response(response_json: dict, request_id: str) -> ClovaOcrResult:
    images = response_json.get("images")
    if not images or not isinstance(images, list):
        logger.warning(
            "CLOVA OCR response missing 'images' field (requestId=%s)", request_id
        )
        raise ClovaOcrRequestFailedError("CLOVA OCR response is missing 'images'")

    image_result = images[0]
    infer_result = image_result.get("inferResult")

    if infer_result != "SUCCESS":
        logger.warning(
            "CLOVA OCR inferResult is not SUCCESS: %s (requestId=%s)",
            infer_result,
            request_id,
        )
        raise ClovaOcrRecognitionFailedError(
            f"CLOVA OCR inferResult is not SUCCESS: {infer_result}"
        )

    fields = image_result.get("fields") or []
    if not fields:
        logger.warning(
            "CLOVA OCR returned no fields (requestId=%s)", request_id
        )
        raise ClovaOcrEmptyResultError("CLOVA OCR returned no fields")

    text, lines = _build_lines_and_text(fields)
    if not text.strip():
        logger.warning(
            "CLOVA OCR returned empty text after parsing fields (requestId=%s)",
            request_id,
        )
        raise ClovaOcrEmptyResultError("CLOVA OCR returned empty text")

    confidence = _calculate_average_confidence(fields)

    logger.info(
        "CLOVA OCR parsed successfully: lines=%d (requestId=%s)",
        len(lines),
        request_id,
    )

    return ClovaOcrResult(
        text=text,
        lines=lines,
        request_id=request_id,
        confidence=confidence,
    )


async def extract_text_from_image(image_bytes: bytes, image_format: str) -> ClovaOcrResult:
    """이미지 bytes를 CLOVA OCR General API로 전달해 텍스트를 추출한다.

    Args:
        image_bytes: 업로드된 이미지의 원본 바이트.
        image_format: CLOVA OCR에 전달할 이미지 포맷 ("jpg" 또는 "png").

    Raises:
        ClovaOcrTimeoutError: 호출이 timeout된 경우.
        ClovaOcrRequestFailedError: 호출 자체가 실패했거나 응답 구조가
            예상과 다른 경우.
        ClovaOcrRecognitionFailedError: inferResult가 SUCCESS가 아닌 경우.
        ClovaOcrEmptyResultError: 인식된 텍스트가 없는 경우.
    """
    request_id = str(uuid.uuid4())
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    request_body = _build_request_body(image_base64, image_format, request_id)

    headers = {
        "X-OCR-SECRET": settings.CLOVA_OCR_SECRET_KEY,
        "Content-Type": "application/json",
    }

    logger.info(
        "Sending CLOVA OCR request (requestId=%s, format=%s)",
        request_id,
        image_format,
    )

    try:
        async with httpx.AsyncClient(timeout=CLOVA_OCR_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.CLOVA_OCR_INVOKE_URL, json=request_body, headers=headers
            )
    except httpx.TimeoutException as exc:
        logger.warning(
            "CLOVA OCR request timed out (requestId=%s)", request_id
        )
        raise ClovaOcrTimeoutError("CLOVA OCR request timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "CLOVA OCR request failed with %s (requestId=%s)",
            type(exc).__name__,
            request_id,
        )
        raise ClovaOcrRequestFailedError("CLOVA OCR request failed") from exc

    logger.info(
        "Received CLOVA OCR response: status=%s (requestId=%s)",
        response.status_code,
        request_id,
    )

    if response.status_code != 200:
        logger.warning(
            "CLOVA OCR returned non-200 status: %s (requestId=%s)",
            response.status_code,
            request_id,
        )
        raise ClovaOcrRequestFailedError(
            f"CLOVA OCR returned unexpected status code: {response.status_code}"
        )

    try:
        response_json = response.json()
    except ValueError as exc:
        logger.warning(
            "CLOVA OCR returned invalid JSON (requestId=%s)", request_id
        )
        raise ClovaOcrRequestFailedError("CLOVA OCR returned invalid JSON") from exc

    return _parse_clova_response(response_json, request_id)
