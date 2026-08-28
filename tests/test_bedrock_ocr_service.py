"""app/services/bedrock_ocr.py 단위 테스트.

실제 AWS Bedrock API를 호출하지 않고 Mock Client를 사용하여
요청 구성, 응답 파싱, 에러 매핑을 검증한다.
"""
import asyncio
from unittest.mock import MagicMock

import botocore.exceptions
import pytest

from app.services import bedrock_ocr


def _run(coro):
    return asyncio.run(coro)


def test_extract_text_success_json():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "text": '{"text": "우리가 빛의 속도로 갈 수 없다면\\n김초엽 소설집", "lines": ["우리가 빛의 속도로 갈 수 없다면", "김초엽 소설집"], "confidence": 0.99}'
                    }
                ],
            }
        },
        "ResponseMetadata": {"RequestId": "bedrock-req-12345"},
    }

    result = _run(
        bedrock_ocr.extract_text_from_image(
            b"fake-image-bytes", "jpg", client=fake_client
        )
    )

    assert result.text == "우리가 빛의 속도로 갈 수 없다면\n김초엽 소설집"
    assert result.lines == ["우리가 빛의 속도로 갈 수 없다면", "김초엽 소설집"]
    assert result.request_id == "bedrock-req-12345"
    assert result.confidence == 0.99


def test_extract_text_success_plain_text():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "text": "우리가 빛의 속도로 갈 수 없다면\n김초엽 소설집"
                    }
                ],
            }
        },
        "ResponseMetadata": {"RequestId": "bedrock-req-12345"},
    }

    result = _run(
        bedrock_ocr.extract_text_from_image(
            b"fake-image-bytes", "jpg", client=fake_client
        )
    )

    assert result.text == "우리가 빛의 속도로 갈 수 없다면\n김초엽 소설집"
    assert result.lines == ["우리가 빛의 속도로 갈 수 없다면", "김초엽 소설집"]
    assert result.request_id == "bedrock-req-12345"
    assert result.confidence == 0.98

    # 검증: converse 인자
    fake_client.converse.assert_called_once()
    kwargs = fake_client.converse.call_args.kwargs
    assert kwargs["modelId"] == bedrock_ocr.settings.BEDROCK_OCR_MODEL_ID
    assert kwargs["messages"][0]["content"][0]["image"]["format"] == "jpeg"
    assert kwargs["messages"][0]["content"][0]["image"]["source"]["bytes"] == b"fake-image-bytes"


def test_extract_text_custom_model_id():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "테스트 결과"}],
            }
        }
    }

    result = _run(
        bedrock_ocr.extract_text_from_image(
            b"fake-image-bytes", "png", model_id="custom.qwen3-vl", client=fake_client
        )
    )

    assert result.text == "테스트 결과"
    assert result.lines == ["테스트 결과"]
    kwargs = fake_client.converse.call_args.kwargs
    assert kwargs["modelId"] == "custom.qwen3-vl"
    assert kwargs["messages"][0]["content"][0]["image"]["format"] == "png"


def test_extract_text_strips_markdown_code_blocks():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "text": "```text\n첫 번째 줄\n두 번째 줄\n```"
                    }
                ],
            }
        }
    }

    result = _run(
        bedrock_ocr.extract_text_from_image(
            b"fake-image-bytes", "png", client=fake_client
        )
    )

    assert result.text == "첫 번째 줄\n두 번째 줄"
    assert result.lines == ["첫 번째 줄", "두 번째 줄"]


def test_empty_content_raises_empty_result_error():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [],
            }
        }
    }

    with pytest.raises(bedrock_ocr.BedrockOcrEmptyResultError):
        _run(
            bedrock_ocr.extract_text_from_image(
                b"fake-image-bytes", "png", client=fake_client
            )
        )


def test_empty_text_raises_empty_result_error():
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "   \n\n  "}],
            }
        }
    }

    with pytest.raises(bedrock_ocr.BedrockOcrEmptyResultError):
        _run(
            bedrock_ocr.extract_text_from_image(
                b"fake-image-bytes", "png", client=fake_client
            )
        )


def test_connect_timeout_raises_timeout_error():
    fake_client = MagicMock()
    fake_client.converse.side_effect = botocore.exceptions.ConnectTimeoutError(
        endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
    )

    with pytest.raises(bedrock_ocr.BedrockOcrTimeoutError):
        _run(
            bedrock_ocr.extract_text_from_image(
                b"fake-image-bytes", "png", client=fake_client
            )
        )


def test_read_timeout_raises_timeout_error():
    fake_client = MagicMock()
    fake_client.converse.side_effect = botocore.exceptions.ReadTimeoutError(
        endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
    )

    with pytest.raises(bedrock_ocr.BedrockOcrTimeoutError):
        _run(
            bedrock_ocr.extract_text_from_image(
                b"fake-image-bytes", "png", client=fake_client
            )
        )


def test_client_error_raises_request_failed_error():
    fake_client = MagicMock()
    fake_client.converse.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Access Denied"}},
        "Converse",
    )

    with pytest.raises(bedrock_ocr.BedrockOcrRequestFailedError) as exc_info:
        _run(
            bedrock_ocr.extract_text_from_image(
                b"fake-image-bytes", "png", client=fake_client
            )
        )

    assert "AccessDeniedException" in str(exc_info.value)


# --- 책 표지 OCR (extract_book_cover_candidates) 테스트 (CLIAR-143) ---
#
# CLOVA와 달리 Bedrock Qwen3-VL은 이미지를 시각적으로 이해하므로, 여러 줄에
# 걸쳐 배치된 하나의 제목도 모델이 직접 하나의 title_candidate로 합쳐서
# 반환하도록 prompt로 요청한다. bounding box 좌표 기반 heuristic은 사용하지
# 않는다.


def _cover_converse_response(json_text: str, request_id: str = "bedrock-cover-req"):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": json_text}],
            }
        },
        "ResponseMetadata": {"RequestId": request_id},
    }


def test_cover_extract_returns_title_author_and_lines():
    """모델이 여러 줄로 나뉜 제목을 이미 하나로 합쳐 반환한 정상 케이스.

    모델이 confidence: 0.95를 응답에 포함하더라도, AWS Bedrock Qwen3-VL이
    CLOVA inferConfidence와 동일한 의미의 공식 OCR confidence를 제공하는
    것이 아니므로 이 값을 신뢰도로 사용하지 않고 항상 None을 반환해야
    한다 (CLIAR-143 최종 수정).
    """
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": "성공하는 인생의 비밀", '
        '"author_candidates": ["이수진 지음"], '
        '"lines": ["성공하는 인생의 비밀", "성공하는 사람들의 비밀을 풀어라!", "이수진 지음"], '
        '"confidence": 0.95}'
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.title_candidate == "성공하는 인생의 비밀"
    assert result.author_candidates == ["이수진 지음"]
    assert result.lines == [
        "성공하는 인생의 비밀",
        "성공하는 사람들의 비밀을 풀어라!",
        "이수진 지음",
    ]
    assert result.confidence is None
    assert result.request_id == "bedrock-cover-req"


def test_cover_extract_ignores_model_confidence_even_when_high():
    """모델 응답에 confidence: 0.99가 포함되어 있어도 결과 confidence는
    항상 None이어야 한다 (모델이 생성한 confidence 숫자를 신뢰도 값으로
    사용하지 않는다)."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": "제목", "author_candidates": ["저자 지음"], '
        '"lines": ["제목", "저자 지음"], "confidence": 0.99}'
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.confidence is None
    # confidence 외 다른 필드는 정상적으로 모델 응답을 그대로 사용해야 한다.
    assert result.title_candidate == "제목"
    assert result.author_candidates == ["저자 지음"]
    assert result.lines == ["제목", "저자 지음"]


def test_cover_extract_uses_cover_specific_prompt_and_model():
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": "제목", "author_candidates": [], "lines": ["제목"]}'
    )

    _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "png", model_id="custom.qwen3-vl", client=fake_client
        )
    )

    kwargs = fake_client.converse.call_args.kwargs
    assert kwargs["modelId"] == "custom.qwen3-vl"
    assert kwargs["messages"][0]["content"][0]["image"]["format"] == "png"
    prompt_text = kwargs["messages"][0]["content"][1]["text"]
    assert "title_candidate" in prompt_text
    assert "author_candidates" in prompt_text


def test_cover_extract_does_not_fabricate_title_or_author_when_uncertain():
    """모델이 제목/저자를 확신하지 못하면 null/빈 배열을 그대로 유지해야 한다."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": null, "author_candidates": [], '
        '"lines": ["알 수 없는 이미지"], "confidence": null}'
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.title_candidate is None
    assert result.author_candidates == []
    assert result.lines == ["알 수 없는 이미지"]
    assert result.confidence is None


def test_cover_extract_strips_markdown_code_fence():
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '```json\n{"title_candidate": "제목", "author_candidates": ["저자 지음"], '
        '"lines": ["제목", "저자 지음"]}\n```'
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.title_candidate == "제목"
    assert result.author_candidates == ["저자 지음"]


def test_cover_extract_malformed_json_does_not_fabricate_candidates():
    """JSON 파싱에 실패하면 title/author를 억지로 만들지 않고 원문만 줄 단위로 보존한다."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        "이것은 JSON이 아닌 일반 텍스트 응답입니다\n두 번째 줄"
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.title_candidate is None
    assert result.author_candidates == []
    assert result.lines == ["이것은 JSON이 아닌 일반 텍스트 응답입니다", "두 번째 줄"]


def test_cover_extract_no_confidence_field_returns_none_not_fabricated():
    """모델이 confidence 필드를 아예 주지 않아도 None을 반환한다."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": "제목", "author_candidates": [], "lines": ["제목"]}'
    )

    result = _run(
        bedrock_ocr.extract_book_cover_candidates(
            b"fake-cover-bytes", "jpg", client=fake_client
        )
    )

    assert result.confidence is None


def test_cover_extract_empty_result_raises_empty_result_error():
    """title/author/lines 전부 없으면 인식할 내용이 없는 것으로 보고 오류를 발생시킨다."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _cover_converse_response(
        '{"title_candidate": null, "author_candidates": [], "lines": []}'
    )

    with pytest.raises(bedrock_ocr.BedrockOcrEmptyResultError):
        _run(
            bedrock_ocr.extract_book_cover_candidates(
                b"fake-cover-bytes", "jpg", client=fake_client
            )
        )


def test_cover_extract_connect_timeout_raises_timeout_error():
    fake_client = MagicMock()
    fake_client.converse.side_effect = botocore.exceptions.ConnectTimeoutError(
        endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
    )

    with pytest.raises(bedrock_ocr.BedrockOcrTimeoutError):
        _run(
            bedrock_ocr.extract_book_cover_candidates(
                b"fake-cover-bytes", "jpg", client=fake_client
            )
        )


def test_cover_extract_client_error_raises_request_failed_error():
    fake_client = MagicMock()
    fake_client.converse.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "Converse",
    )

    with pytest.raises(bedrock_ocr.BedrockOcrRequestFailedError):
        _run(
            bedrock_ocr.extract_book_cover_candidates(
                b"fake-cover-bytes", "jpg", client=fake_client
            )
        )


def test_sentence_ocr_prompt_and_cover_ocr_prompt_are_independent():
    """sentence OCR 호출이 cover 전용 prompt를 사용하지 않는지(회귀 방지) 확인한다."""
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "일반 문장"}]}}
    }

    _run(
        bedrock_ocr.extract_text_from_image(
            b"fake-image-bytes", "jpg", client=fake_client
        )
    )

    prompt_text = fake_client.converse.call_args.kwargs["messages"][0]["content"][1]["text"]
    assert "title_candidate" not in prompt_text
    assert "author_candidates" not in prompt_text
