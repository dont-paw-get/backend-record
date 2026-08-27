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
