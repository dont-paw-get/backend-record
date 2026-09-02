"""AWS Bedrock (Qwen3-VL 등) 기반 OCR 서비스.

Bedrock Runtime Converse API를 호출하여 이미지 내 텍스트를 추출하고 줄 단위로 가공한다.
CLOVA OCR과 동일한 인터페이스 규격을 제공하여 상호 교체가 가능하다.
"""
import asyncio
from dataclasses import dataclass
import logging
import re
import threading
import uuid

import boto3
import botocore.exceptions

from botocore.config import Config
from opentelemetry import trace

from app.core.config import settings

logger = logging.getLogger(__name__)

# OCR 처리(이미지 축소 + Bedrock 호출 + 응답 파싱)를 하나로 묶는 상위 span.
# botocore instrumentation 이 만드는 Bedrock 호출 span 은 이 span 의 자식이
# 된다. 함수 단위로 세분화하지 않고 이 한 개만 둔다.
_tracer = trace.get_tracer(__name__)


class BedrockOcrError(Exception):
    """Bedrock OCR 연동 관련 오류의 베이스 클래스."""


class BedrockOcrTimeoutError(BedrockOcrError):
    """Bedrock API 호출이 timeout된 경우."""


class BedrockOcrRequestFailedError(BedrockOcrError):
    """Bedrock API 호출 실패 또는 비정상 응답인 경우."""


class BedrockOcrEmptyResultError(BedrockOcrError):
    """Bedrock 모델이 응답을 반환했으나 인식된 텍스트가 없는 경우."""


@dataclass(frozen=True)
class BedrockOcrResult:
    """Bedrock OCR 처리 결과."""

    text: str
    lines: list[str]
    request_id: str
    confidence: float | None = None
    language: str | None = None


@dataclass(frozen=True)
class BedrockOcrCoverResult:
    """책 표지 OCR 결과.

    Bedrock Qwen3-VL은 이미지를 시각적으로 이해하므로, 여러 줄에 걸쳐
    배치된 하나의 제목도 모델이 직접 하나의 title_candidate로 결합해
    반환한다(bounding box 좌표 기반 heuristic을 사용하지 않는다). OCR만
    으로 제목/저자를 100% 확정할 수 없으므로 확정값이 아닌 "후보"이며,
    모델이 확신하지 못하면 None/빈 목록으로 그대로 유지한다.
    """

    title_candidate: str | None
    author_candidates: list[str]
    lines: list[str]
    request_id: str
    confidence: float | None = None
    isbn: str | None = None


def get_bedrock_runtime_client():
    """설정된 환경변수 또는 프로필에 맞춰 boto3 Bedrock-Runtime 클라이언트를 생성한다."""
    session_kwargs = {}
    if settings.AWS_PROFILE:
        session_kwargs["profile_name"] = settings.AWS_PROFILE
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.AWS_SESSION_TOKEN:
            session_kwargs["aws_session_token"] = settings.AWS_SESSION_TOKEN


    boto_config = Config(
        retries={
            "max_attempts": 6,
            "mode": "adaptive",
        },
        connect_timeout=15,
        read_timeout=60,
    )
    session = boto3.Session(**session_kwargs)
    # Bedrock 은 모델이 존재하는 전용 리전(BEDROCK_REGION, 기본 us-east-1)으로
    # 호출한다. 파드의 AWS_REGION(서울)과 분리해 두어야 서비스 홈 리전은 유지하면서
    # Qwen3-VL 을 호출할 수 있다.
    return session.client("bedrock-runtime", region_name=settings.BEDROCK_REGION, config=boto_config)


# boto3 클라이언트 생성은 서비스 모델 로딩 + 자격증명 체인 해석(IRSA 시 네트워크
# 조회 포함)이 있어 요청당 수십~수백 ms가 든다. 저수준 boto3 클라이언트는 메서드
# 호출에 대해 thread-safe 하므로(생성만 thread-safe 하지 않다) 한 번 만들어 모든
# 요청이 재사용한다. 생성 경합은 lock 으로 막고, 최초 1회만 만든다.
_cached_bedrock_client = None
_bedrock_client_lock = threading.Lock()


def _get_cached_bedrock_runtime_client():
    """프로세스 전역에서 재사용하는 Bedrock-Runtime 클라이언트를 반환한다."""
    global _cached_bedrock_client
    if _cached_bedrock_client is None:
        with _bedrock_client_lock:
            if _cached_bedrock_client is None:
                _cached_bedrock_client = get_bedrock_runtime_client()
    return _cached_bedrock_client


def _normalize_image_format(image_format: str) -> str:
    """Bedrock Converse API에 호환되는 이미지 포맷 문자열로 변환한다."""
    fmt = image_format.lower().lstrip(".")
    if fmt in ("jpg", "jpeg"):
        return "jpeg"
    if fmt in ("png", "webp", "gif"):
        return fmt
    return "jpeg"


# 모델에 보내기 전에 이미지의 긴 변을 이 값 이하로 축소한다. 폰 카메라 원본
# (4000px대)을 그대로 보내면 vision 토큰이 폭증해 prefill 지연이 커진다.
# 2048px는 책 문장/표지 텍스트 가독성을 유지하면서도 큰 이미지의 처리량을
# 크게 줄이는 절충값이다. 이보다 작은 이미지는 그대로 사용한다.
_MAX_IMAGE_DIMENSION = 2048


def _downscale_image_if_needed(image_bytes: bytes, normalized_format: str) -> bytes:
    """긴 변이 _MAX_IMAGE_DIMENSION을 넘는 이미지는 비율을 유지하며 축소한다.

    축소가 불필요하거나 디코딩에 실패하면 원본 바이트를 그대로 반환한다.
    (여기서 예외를 던져 OCR을 막지 않는다. 잘못된 이미지 판정은 모델에 맡긴다.)
    """
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(image_bytes)) as img:
            longest = max(img.size)
            if longest <= _MAX_IMAGE_DIMENSION:
                return image_bytes

            img = img.copy()
            img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION))

            pil_format = "JPEG" if normalized_format == "jpeg" else normalized_format.upper()
            if pil_format == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            buffer = BytesIO()
            img.save(buffer, format=pil_format)
            return buffer.getvalue()
    except Exception:  # noqa: BLE001 - 축소 실패 시 원본 유지 (OCR 자체는 진행)
        logger.warning("이미지 축소에 실패하여 원본 이미지를 사용합니다.", exc_info=True)
        return image_bytes


def _detect_language(text: str) -> str:
    """텍스트의 문자 집합을 기반으로 한/중/일/영 주요 언어를 판별한다."""
    has_hangul = False
    has_kana = False
    has_hanzi = False
    has_latin = False

    for ch in text:
        code = ord(ch)
        # 한글 음절 및 자모
        if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            has_hangul = True
        # 일본어 히라가나, 가타카나
        elif 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
            has_kana = True
        # 한자 (CJK 통합 한자)
        elif 0x4E00 <= code <= 0x9FFF:
            has_hanzi = True
        # 라틴 알파벳
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            has_latin = True

    if has_hangul:
        return "ko"
    if has_kana:
        return "ja"
    if has_hanzi:
        return "zh"
    if has_latin:
        return "en"
    return "ko"


def _parse_extracted_content(raw_text: str) -> tuple[str, list[str], float | None, str | None]:
    """모델 출력에서 text, lines, confidence, language를 추출한다."""
    import json

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        else:
            cleaned = ""
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # 1. JSON 구조 파싱 시도
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            text = str(data.get("text", "")).strip()
            lines = data.get("lines")
            if isinstance(lines, list) and lines:
                lines = [str(line).strip() for line in lines if str(line).strip()]
            else:
                lines = [line.strip() for line in text.splitlines() if line.strip()]

            if not text and lines:
                text = "\n".join(lines)

            confidence = data.get("confidence")
            if isinstance(confidence, (int, float)):
                confidence = round(max(0.0, min(1.0, float(confidence))), 2)
            else:
                confidence = 0.98

            language = data.get("language")
            if not language or language not in ("ko", "en", "ja", "zh", "mixed"):
                language = _detect_language(text)

            return text, lines, confidence, language
    except Exception:
        pass

    # 2. 일반 텍스트 파싱 폴백
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    text = "\n".join(lines)
    confidence = 0.98 if text else None
    language = _detect_language(text) if text else None
    return text, lines, confidence, language


SENTENCE_OCR_PROMPT = (
    "이미지에 적힌 모든 텍스트를 보이는 원문 그대로 추출하고, "
    "인식된 텍스트의 선명도와 정확도를 바탕으로 신뢰도(0.00 ~ 1.00)를 측정하여 반드시 아래 JSON 형식으로만 응답해줘.\n"
    "- 대상 언어: 한국어(ko), 영어(en), 일본어(ja), 중국어(zh)\n"
    "- 한글, 영문 대소문자, 일본어(가나/한자), 중국어(간체/번체) 원문 표기를 그대로 유지\n"
    "- 설명, 번역, 사족 없이 반드시 아래 JSON 형식으로만 출력:\n"
    "{\n"
    '  "text": "줄바꿈(\\n)으로 연결된 전체 원문 텍스트",\n'
    '  "lines": ["줄1", "줄2"],\n'
    '  "language": "ko" | "en" | "ja" | "zh" | "mixed",\n'
    '  "confidence": 0.98\n'
    "}"
)

# 책 표지 전용 prompt. CLOVA 기반 구현(CLIAR-131/136/142)은 bounding box
# 좌표로 글자 크기를 비교해 제목을 추정했지만, 그 방식은 제목이 여러 줄에
# 걸쳐 배치된 경우(CLIAR-142에서 발견) 하나로 결합하지 못하는 한계가 있었다.
# Qwen3-VL은 이미지를 시각적으로 이해하므로, 여러 줄에 걸친 제목을 모델이
# 직접 하나의 title_candidate로 결합해 반환하도록 요청한다. 모델이 이미지에
# 없는 정보를 추측하거나 외부 지식(ISBN 검색, 저자 추측 등)으로 보완하지
# 않도록 명시적으로 금지한다.
COVER_OCR_PROMPT = (
    "이 이미지는 책 표지다. 이미지에서 실제로 보이는 텍스트만 사용해서 "
    "아래 JSON 형식으로만 응답해줘.\n"
    "- title_candidate: 표지에 인쇄된 책 제목. 제목이 여러 줄로 나뉘어 있으면 "
    "하나의 문자열로 합쳐라. 부제(sub title)는 제목에 포함하지 마라. 제목을 "
    "확신할 수 없으면 null로 응답해라.\n"
    "- author_candidates: 저자/역자/편저자 표기(예: '지음', '옮김', '저', '편저' 등)가 "
    "함께 적힌 텍스트 목록. 확신할 수 없으면 빈 배열로 응답해라.\n"
    "- lines: 표지에서 인식한 전체 텍스트를 줄 단위로 나눈 목록.\n\n"
    "중요:\n"
    "- 이미지에 실제로 보이지 않는 텍스트를 만들어내지 마라.\n"
    "- ISBN 검색, 인터넷 검색, 외부 지식으로 저자나 제목을 추측/보완하지 마라.\n"
    "- 제목이나 저자를 창작하거나 교정하지 마라.\n"
    "- 설명, 번역, 사족 없이 반드시 아래 JSON 형식으로만 출력:\n"
    "{\n"
    '  "title_candidate": "책 제목" | null,\n'
    '  "author_candidates": ["저자 지음"],\n'
    '  "lines": ["줄1", "줄2"]\n'
    "}"
)


def _invoke_converse(
    client,
    image_bytes: bytes,
    image_format: str,
    model_id: str,
    request_id: str,
    prompt_text: str,
) -> tuple[str, str]:
    """Bedrock Converse API를 호출하고 (모델 응답 원문, 실제 request_id)를 반환한다.

    sentence OCR과 cover OCR이 공통으로 사용하는 HTTP 호출/오류 처리
    로직이다. 이후 응답 파싱(JSON 구조 해석)만 호출부마다 다르다.

    Raises:
        BedrockOcrTimeoutError: 호출이 timeout된 경우.
        BedrockOcrRequestFailedError: 호출 실패, 응답 구조 이상.
        BedrockOcrEmptyResultError: content가 비어 있는 경우.
    """
    normalized_format = _normalize_image_format(image_format)
    # 큰 원본 이미지는 prefill 지연을 줄이기 위해 전송 전에 축소한다.
    image_bytes = _downscale_image_if_needed(image_bytes, normalized_format)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "image": {
                        "format": normalized_format,
                        "source": {
                            "bytes": image_bytes,
                        },
                    }
                },
                {
                    "text": (
                        "이미지에 적힌 모든 텍스트를 보이는 원문 그대로 추출하고, "
                        "인식된 텍스트의 선명도와 정확도를 바탕으로 신뢰도(0.00 ~ 1.00)를 측정하여 반드시 아래 JSON 형식으로만 응답해줘.\n"
                        "- 대상 언어: 한국어(ko), 영어(en), 일본어(ja), 중국어(zh)\n"
                        "- 한글, 영문 대소문자, 일본어(가나/한자), 중국어(간체/번체) 원문 표기를 그대로 유지\n"
                        "- 각 줄을 lines 배열에 순서대로 담고, 설명·번역·사족 없이 아래 JSON 형식으로만 출력:\n"
                        "{\n"
                        '  "lines": ["줄1", "줄2"],\n'
                        '  "language": "ko" | "en" | "ja" | "zh" | "mixed",\n'
                        '  "confidence": 0.98\n'
                        "}"
                    )
                },
            ],
        }
    ]

    logger.info(
        "Sending Bedrock OCR request (requestId=%s, modelId=%s, format=%s)",
        request_id,
        model_id,
        normalized_format,
    )

    try:
        response = client.converse(
            modelId=model_id,
            messages=messages,
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0,
            },
        )
    except (botocore.exceptions.ConnectTimeoutError, botocore.exceptions.ReadTimeoutError) as exc:
        logger.warning("Bedrock OCR request timed out (requestId=%s, modelId=%s)", request_id, model_id)
        raise BedrockOcrTimeoutError("Bedrock OCR request timed out") from exc
    except botocore.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        logger.warning(
            "Bedrock OCR request failed with %s: %s (requestId=%s)",
            error_code,
            exc,
            request_id,
        )
        raise BedrockOcrRequestFailedError(f"Bedrock OCR request failed: {error_code}") from exc
    except Exception as exc:
        logger.warning(
            "Bedrock OCR request failed unexpectedly: %s (requestId=%s)",
            type(exc).__name__,
            request_id,
        )
        raise BedrockOcrRequestFailedError("Bedrock OCR request failed") from exc

    try:
        output_message = response.get("output", {}).get("message", {})
        content_list = output_message.get("content", [])
        if not content_list or not isinstance(content_list, list):
            raise BedrockOcrEmptyResultError("Bedrock OCR returned empty content")

        raw_text = content_list[0].get("text", "")
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Failed to parse Bedrock response structure (requestId=%s)", request_id)
        raise BedrockOcrRequestFailedError("Failed to parse Bedrock response") from exc

    req_id = response.get("ResponseMetadata", {}).get("RequestId") or request_id
    return raw_text, req_id


def _sync_invoke_converse(
    client, image_bytes: bytes, image_format: str, model_id: str, request_id: str
) -> BedrockOcrResult:
    """동기적으로 Bedrock Converse API를 호출해 문장 OCR 결과를 얻는다."""
    raw_text, req_id = _invoke_converse(
        client, image_bytes, image_format, model_id, request_id, SENTENCE_OCR_PROMPT
    )

    text, lines, confidence, language = _parse_extracted_content(raw_text)
    if not text.strip():
        logger.warning("Bedrock OCR returned empty text (requestId=%s)", req_id)
        raise BedrockOcrEmptyResultError("Bedrock OCR returned empty text")

    logger.info(
        "Bedrock OCR parsed successfully: lines=%d, lang=%s, confidence=%s (requestId=%s)",
        len(lines),
        language,
        confidence,
        req_id,
    )

    return BedrockOcrResult(
        text=text,
        lines=lines,
        request_id=req_id,
        confidence=confidence,
        language=language,
    )


# ISBN 표기에서 숫자(및 ISBN-10 체크숫자 X)만 남기기 위한 정규식.
_ISBN_NON_DIGIT_RE = re.compile(r"[^0-9Xx]")


def _extract_isbn(lines: list[str]) -> str | None:
    """
    OCR 줄 목록에서 ISBN을 찾아 하이픈·공백을 제거한 숫자 문자열로 반환한다.
    """
    # 'ISBN' 라벨이 붙은 줄을 먼저, 그다음 나머지 줄을 검사한다.
    # 라벨 줄이 부가기호 등으로 매치에 실패해도 바코드 아래 순수 숫자 줄을
    # 놓치지 않도록 candidates에서 제외하지 않는다.
    labeled = [line for line in lines if "ISBN" in line.upper()]
    others = [line for line in lines if "ISBN" not in line.upper()]

    for line in labeled + others:
        digits = _ISBN_NON_DIGIT_RE.sub("", line).upper()
        # ISBN-13: 978/979 접두사 + 13자리 숫자. 한국 책 표지에는 ISBN 뒤에
        # 5자리 부가기호(예: 'ISBN 979-11-86343-13-5 03810')가 함께 인쇄되는
        # 경우가 많으므로, 선행 13자리만 잘라서 검사한다.
        if len(digits) >= 13 and digits[:13].isdigit() and digits[:3] in ("978", "979"):
            return digits[:13]
        # ISBN-10: 9자리 숫자 + 체크숫자(0~9 또는 X)
        if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] == "X"):
            return digits
    return None


def _parse_cover_content(raw_text: str) -> tuple[str | None, list[str], list[str]]:
    """
    책 표지 OCR 모델 응답에서 title/author/lines를 추출한다.
    """
    import json

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1 :] if first_newline != -1 else ""
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        data = None

    if isinstance(data, dict):
        title_candidate = data.get("title_candidate")
        title_candidate = str(title_candidate).strip() if title_candidate else None

        author_candidates = data.get("author_candidates")
        if isinstance(author_candidates, list):
            author_candidates = [str(a).strip() for a in author_candidates if str(a).strip()]
        else:
            author_candidates = []

        lines = data.get("lines")
        if isinstance(lines, list):
            lines = [str(line).strip() for line in lines if str(line).strip()]
        else:
            lines = []

        return title_candidate, author_candidates, lines

    # JSON 구조가 아니면 title/author를 추측하지 않고, 원문만 줄 단위로 보존한다.
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return None, [], lines


def _sync_invoke_cover_converse(
    client, image_bytes: bytes, image_format: str, model_id: str, request_id: str
) -> BedrockOcrCoverResult:
    """동기적으로 Bedrock Converse API를 호출해 책 표지 OCR 결과를 얻는다."""
    raw_text, req_id = _invoke_converse(
        client, image_bytes, image_format, model_id, request_id, COVER_OCR_PROMPT
    )

    title_candidate, author_candidates, lines = _parse_cover_content(raw_text)

    if not title_candidate and not author_candidates and not lines:
        logger.warning("Bedrock cover OCR returned empty result (requestId=%s)", req_id)
        raise BedrockOcrEmptyResultError("Bedrock cover OCR returned empty result")

    isbn = _extract_isbn(lines)

    logger.info(
        "Bedrock cover OCR parsed successfully: has_title=%s, "
        "author_candidate_count=%d, lines=%d (requestId=%s)",
        title_candidate is not None,
        len(author_candidates),
        len(lines),
        req_id,
    )

    # CLIAR-143 최종 수정: AWS Bedrock Qwen3-VL이 생성한 confidence 값은
    # CLOVA inferConfidence와 동일한 의미의 공식 OCR confidence가 아니므로
    # 신뢰도 값으로 사용하지 않는다. API contract는 유지하되 항상 None을
    # 반환한다.
    return BedrockOcrCoverResult(
        title_candidate=title_candidate,
        author_candidates=author_candidates,
        lines=lines,
        request_id=req_id,
        confidence=None,
        isbn=isbn,
    )


async def extract_text_from_image(
    image_bytes: bytes,
    image_format: str,
    model_id: str | None = None,
    client=None,
) -> BedrockOcrResult:
    """이미지 bytes를 AWS Bedrock (Qwen3-VL 등)에 전달하여 OCR 텍스트를 추출한다.

    Args:
        image_bytes: 업로드된 이미지 바이트.
        image_format: 이미지 형식 ("jpg", "png", "jpeg" 등).
        model_id: 사용할 Bedrock 모델 ID (미지정 시 설정값 BEDROCK_OCR_MODEL_ID 사용).
        client: 테스트나 사용자 정의 boto3 클라이언트 주입용.

    Raises:
        BedrockOcrTimeoutError: API 호출 시간 초과 시.
        BedrockOcrRequestFailedError: API 호출 실패 또는 비정상 응답 시.
        BedrockOcrEmptyResultError: 인식된 텍스트가 없는 경우.
    """
    target_model_id = model_id or settings.BEDROCK_OCR_MODEL_ID
    request_id = str(uuid.uuid4())
    bedrock_client = client or _get_cached_bedrock_runtime_client()

    with _tracer.start_as_current_span("record.ocr") as span:
        span.set_attribute("record.ocr.type", "sentences")
        span.set_attribute("record.ocr.image_format", _normalize_image_format(image_format))
        span.set_attribute("record.ocr.image_bytes", len(image_bytes))
        span.set_attribute("record.ocr.model_id", target_model_id)

        result = await asyncio.to_thread(
            _sync_invoke_converse,
            bedrock_client,
            image_bytes,
            image_format,
            target_model_id,
            request_id,
        )

        span.set_attribute("record.ocr.line_count", len(result.lines))
        if result.language:
            span.set_attribute("record.ocr.language", result.language)
        return result


async def extract_book_cover_candidates(
    image_bytes: bytes,
    image_format: str,
    model_id: str | None = None,
    client=None,
) -> BedrockOcrCoverResult:
    """
    책 표지 이미지를 AWS Bedrock (Qwen3-VL 등)에 전달해 제목/저자 후보를 추출한다.
    """
    target_model_id = model_id or settings.BEDROCK_OCR_MODEL_ID
    request_id = str(uuid.uuid4())
    bedrock_client = client or _get_cached_bedrock_runtime_client()

    with _tracer.start_as_current_span("record.ocr") as span:
        span.set_attribute("record.ocr.type", "cover")
        span.set_attribute("record.ocr.image_format", _normalize_image_format(image_format))
        span.set_attribute("record.ocr.image_bytes", len(image_bytes))
        span.set_attribute("record.ocr.model_id", target_model_id)

        result = await asyncio.to_thread(
            _sync_invoke_cover_converse,
            bedrock_client,
            image_bytes,
            image_format,
            target_model_id,
            request_id,
        )

        span.set_attribute("record.ocr.line_count", len(result.lines))
        span.set_attribute("record.ocr.isbn_detected", result.isbn is not None)
        return result
