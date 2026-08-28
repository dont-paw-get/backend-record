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


@dataclass(frozen=True)
class ClovaOcrCoverResult:
    """책 표지 OCR 결과를 애플리케이션 레벨로 가공한 결과.

    OCR만으로 제목/저자를 100% 확정할 수 없으므로, 확정값이 아닌
    "후보"로 표현한다. 추출 근거가 부족하면 None/빈 목록을 반환하며
    억지로 값을 채우지 않는다.
    """

    title_candidate: str | None
    author_candidates: list[str]
    lines: list[str]
    request_id: str
    confidence: float | None


# 책 표지에서 저자/역자를 나타낼 때 흔히 함께 쓰이는 표기.
#
# "지음"/"옮김"/"엮음"/"편저"처럼 2글자 이상인 표기는 일반 단어 내부에
# 우연히 포함될 가능성이 낮아 부분 문자열(substring) 매칭으로 판별한다.
AUTHOR_MARKER_KEYWORDS_SUBSTRING = ("지음", "옮김", "엮음", "편저")

# "저"/"역"/"글"처럼 한 글자 표기는 "저장", "역사", "역량", "글자", "글쓰기"
# 등 일반 단어 내부에 흔히 포함되어 단순 substring 매칭으로는 오탐이
# 발생한다(CLIAR-136). 저자 표기로 쓰일 때는 대개 "이름 + 공백 + marker"
# 형태로 줄 끝에 독립된 단어로 등장하므로, 공백으로 구분된 마지막 토큰이
# marker와 정확히 일치할 때만 저자 표기로 인정한다.
AUTHOR_MARKER_KEYWORDS_STANDALONE_SUFFIX = ("저", "역", "글")


def _line_has_author_marker(line: str) -> bool:
    """줄이 실제 저자/역자 표기를 포함하는지 판별한다.

    - 2글자 이상 marker("지음" 등): 부분 문자열로만 있어도 인정한다.
    - 1글자 marker("저"/"역"/"글"): 공백으로 구분된 마지막 토큰이 marker와
      정확히 같을 때만 인정한다. 이렇게 하면 "저장한 문장"처럼 marker가
      단어 중간에 섞여 있는 경우를 배제하면서, "한강 저"처럼 독립된
      토큰으로 쓰인 정상 표기는 그대로 인식한다.
    """
    if any(keyword in line for keyword in AUTHOR_MARKER_KEYWORDS_SUBSTRING):
        return True

    tokens = line.split()
    if tokens and tokens[-1] in AUTHOR_MARKER_KEYWORDS_STANDALONE_SUFFIX:
        return True

    return False


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


def _group_fields_into_lines(fields: list[dict]) -> list[list[dict]]:
    """CLOVA OCR fields[]를 lineBreak 기준으로 같은 줄에 속한 field끼리 묶는다.

    sentence OCR과 cover OCR이 공통으로 사용하는 그룹핑 로직이다.
    """
    lines: list[list[dict]] = []
    current_line: list[dict] = []

    for field in fields:
        if field.get("inferText", ""):
            current_line.append(field)

        if field.get("lineBreak") and current_line:
            lines.append(current_line)
            current_line = []

    if current_line:
        lines.append(current_line)

    return lines


def _build_lines_and_text(fields: list[dict]) -> tuple[str, list[str]]:
    """CLOVA OCR fields[]를 lineBreak 기준으로 줄 단위 텍스트로 재구성한다.

    같은 줄에 속한 서로 다른 field는 별도의 단어/어절 단위로 인식된 것이므로
    공백 1칸으로 연결한다. NLP/문장 교정은 수행하지 않는다.
    """
    line_groups = _group_fields_into_lines(fields)
    lines = [
        " ".join(field["inferText"] for field in line_group)
        for line_group in line_groups
    ]
    text = "\n".join(lines)
    return text, lines


def _line_box_height(line_fields: list[dict]) -> float | None:
    """줄에 속한 field들의 boundingPoly.vertices에서 세로 높이를 계산한다.

    CLOVA General V2는 version="V2"일 때만 boundingPoly를 제공한다.
    좌표 정보가 없으면 None을 반환하며, 이 경우 글자 크기를 알 수 없으므로
    호출부는 이 줄을 제목 크기 비교 대상에서 제외해야 한다.
    """
    heights: list[float] = []
    for field in line_fields:
        vertices = (field.get("boundingPoly") or {}).get("vertices") or []
        ys = [v["y"] for v in vertices if isinstance(v, dict) and "y" in v]
        if len(ys) >= 2:
            heights.append(max(ys) - min(ys))

    if not heights:
        return None
    return sum(heights) / len(heights)


def _extract_title_candidate(line_groups: list[list[dict]], lines: list[str]) -> str | None:
    """표지에서 가장 큰 글씨로 인쇄된 줄을 제목 후보로 삼는다.

    책 표지는 제목을 가장 크게 배치하는 경우가 많다는 일반적인 경향을
    이용한 단순 규칙이며, 100% 정확성을 보장하지 않는다. boundingPoly
    좌표가 전혀 없어 글자 크기를 비교할 수 없으면 억지로 추측하지 않고
    None을 반환한다.
    """
    heights = [_line_box_height(line_group) for line_group in line_groups]
    measurable = [(h, line) for h, line in zip(heights, lines) if h is not None]

    if not measurable:
        return None

    _, largest_line = max(measurable, key=lambda pair: pair[0])
    return largest_line


def _extract_author_candidates(lines: list[str]) -> list[str]:
    """'지음/글/옮김' 등 저자 표기가 포함된 줄만 저자 후보로 삼는다.

    저자 표기가 전혀 없으면 어떤 줄이 저자인지 근거가 없으므로 억지로
    추측하지 않고 빈 목록을 반환한다.
    """
    return [line for line in lines if _line_has_author_marker(line)]


def _calculate_average_confidence(fields: list[dict]) -> float | None:
    confidences = [
        field["inferConfidence"]
        for field in fields
        if isinstance(field.get("inferConfidence"), (int, float))
    ]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)


def _extract_success_fields(response_json: dict, request_id: str) -> list[dict]:
    """CLOVA 응답에서 SUCCESS 여부를 확인하고 fields[]를 꺼낸다.

    sentence OCR과 cover OCR이 공통으로 사용하는 검증 단계이다.
    """
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

    return fields


def _parse_clova_response(response_json: dict, request_id: str) -> ClovaOcrResult:
    fields = _extract_success_fields(response_json, request_id)

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


def _parse_clova_cover_response(response_json: dict, request_id: str) -> ClovaOcrCoverResult:
    fields = _extract_success_fields(response_json, request_id)

    line_groups = _group_fields_into_lines(fields)
    lines = [
        " ".join(field["inferText"] for field in line_group) for line_group in line_groups
    ]

    if not any(line.strip() for line in lines):
        logger.warning(
            "CLOVA OCR returned empty text after parsing fields (requestId=%s)",
            request_id,
        )
        raise ClovaOcrEmptyResultError("CLOVA OCR returned empty text")

    title_candidate = _extract_title_candidate(line_groups, lines)
    author_candidates = _extract_author_candidates(lines)
    confidence = _calculate_average_confidence(fields)

    logger.info(
        "CLOVA OCR cover parsed successfully: lines=%d, has_title=%s, "
        "author_candidate_count=%d (requestId=%s)",
        len(lines),
        title_candidate is not None,
        len(author_candidates),
        request_id,
    )

    return ClovaOcrCoverResult(
        title_candidate=title_candidate,
        author_candidates=author_candidates,
        lines=lines,
        request_id=request_id,
        confidence=confidence,
    )


async def _call_clova_ocr(image_bytes: bytes, image_format: str, request_id: str) -> dict:
    """CLOVA OCR General API를 호출하고 응답 JSON을 반환한다.

    sentence OCR과 cover OCR이 공통으로 사용하는 HTTP 호출 로직이다.
    요청 payload 구성, timeout/HTTP 오류 처리, status/JSON 검증까지
    이 함수 하나로 통일해 두 벌의 CLOVA 호출 코드가 생기지 않도록 한다.

    Raises:
        ClovaOcrTimeoutError: 호출이 timeout된 경우.
        ClovaOcrRequestFailedError: 호출 자체가 실패했거나 응답 구조가
            예상과 다른 경우.
    """
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
        return response.json()
    except ValueError as exc:
        logger.warning(
            "CLOVA OCR returned invalid JSON (requestId=%s)", request_id
        )
        raise ClovaOcrRequestFailedError("CLOVA OCR returned invalid JSON") from exc


async def extract_text_from_image(image_bytes: bytes, image_format: str) -> ClovaOcrResult:
    """이미지 bytes를 CLOVA OCR General API로 전달해 문장 텍스트를 추출한다.

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
    response_json = await _call_clova_ocr(image_bytes, image_format, request_id)
    return _parse_clova_response(response_json, request_id)


async def extract_book_cover_candidates(
    image_bytes: bytes, image_format: str
) -> ClovaOcrCoverResult:
    """책 표지 이미지에서 CLOVA OCR로 텍스트를 추출하고 제목/저자 후보를 도출한다.

    sentence OCR(extract_text_from_image)과 동일한 CLOVA HTTP 호출
    로직(_call_clova_ocr)을 재사용하며, 결과 후처리(제목/저자 후보 추출)만
    다르다. OCR만으로 제목/저자를 확정할 수 없으므로 결과는 "후보"이며,
    추출 근거가 부족하면 None/빈 목록을 반환한다.

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
    response_json = await _call_clova_ocr(image_bytes, image_format, request_id)
    return _parse_clova_cover_response(response_json, request_id)
