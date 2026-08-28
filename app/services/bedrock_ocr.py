"""AWS Bedrock (Qwen3-VL 등) 기반 OCR 서비스.

Bedrock Runtime Converse API를 호출하여 이미지 내 텍스트를 추출하고 줄 단위로 가공한다.
CLOVA OCR과 동일한 인터페이스 규격을 제공하여 상호 교체가 가능하다.
"""
import asyncio
from dataclasses import dataclass
import logging
import uuid

import boto3
import botocore.exceptions

from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


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
    return session.client("bedrock-runtime", region_name=settings.AWS_REGION, config=boto_config)


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


def _sync_invoke_converse(
    client, image_bytes: bytes, image_format: str, model_id: str, request_id: str
) -> BedrockOcrResult:
    """동기적으로 Bedrock Converse API를 호출한다."""
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

    text, lines, confidence, language = _parse_extracted_content(raw_text)
    if not text.strip():
        logger.warning("Bedrock OCR returned empty text (requestId=%s)", request_id)
        raise BedrockOcrEmptyResultError("Bedrock OCR returned empty text")

    req_id = response.get("ResponseMetadata", {}).get("RequestId") or request_id

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
    bedrock_client = client or get_bedrock_runtime_client()

    return await asyncio.to_thread(
        _sync_invoke_converse,
        bedrock_client,
        image_bytes,
        image_format,
        target_model_id,
        request_id,
    )
