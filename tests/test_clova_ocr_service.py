"""app/services/clova_ocr.py 단위 테스트.

실제 CLOVA OCR API는 호출하지 않고 httpx.AsyncClient를 fake로 대체해
요청 payload 구성, 응답 파싱, 오류 매핑을 검증한다.
"""
import asyncio
import base64
import uuid

import httpx
import pytest

from app.services import clova_ocr

SUCCESS_BODY = {
    "images": [
        {
            "inferResult": "SUCCESS",
            "message": "SUCCESS",
            "fields": [
                {"inferText": "첫", "inferConfidence": 0.99, "lineBreak": False},
                {"inferText": "줄", "inferConfidence": 0.97, "lineBreak": True},
                {"inferText": "두번째", "inferConfidence": 0.95, "lineBreak": True},
            ],
        }
    ]
}


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, json_error: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class _FakeAsyncClient:
    """httpx.AsyncClient를 대체하는 테스트용 fake 클라이언트."""

    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.exception is not None:
            raise self.exception
        return self.response


def _install_fake_client(monkeypatch, response=None, exception=None):
    client = _FakeAsyncClient(response=response, exception=exception)

    def factory(*args, **kwargs):
        return client

    monkeypatch.setattr(clova_ocr.httpx, "AsyncClient", factory)
    return client


def _run(coro):
    return asyncio.run(coro)


def test_request_headers_and_body_match_clova_spec(monkeypatch):
    client = _install_fake_client(monkeypatch, response=_FakeResponse(200, SUCCESS_BODY))

    _run(clova_ocr.extract_text_from_image(b"fake-image-bytes", "jpg"))

    call = client.calls[0]
    assert call["url"] == clova_ocr.settings.CLOVA_OCR_INVOKE_URL
    assert call["headers"]["X-OCR-SECRET"] == clova_ocr.settings.CLOVA_OCR_SECRET_KEY
    assert call["headers"]["Content-Type"] == "application/json"

    body = call["json"]
    assert body["version"] == "V2"
    assert body["lang"] == "ko"
    assert body["enableTableDetection"] is False
    assert isinstance(body["timestamp"], int)
    uuid.UUID(body["requestId"])  # 유효한 UUID 형식인지 확인
    assert body["images"] == [
        {
            "format": "jpg",
            "name": body["images"][0]["name"],
            "data": body["images"][0]["data"],
        }
    ]
    assert body["images"][0]["data"]  # base64 인코딩된 문자열 존재


def test_lines_are_built_using_line_break(monkeypatch):
    _install_fake_client(monkeypatch, response=_FakeResponse(200, SUCCESS_BODY))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    # SUCCESS_BODY의 fields: "첫"(lineBreak False), "줄"(lineBreak True),
    # "두번째"(lineBreak True) -> 같은 줄에 속한 field는 공백으로 연결되고,
    # lineBreak 지점에서 줄이 마무리된다.
    assert result.lines == ["첫 줄", "두번째"]
    assert result.text == "첫 줄\n두번째"


def test_same_line_fields_are_joined_with_a_single_space(monkeypatch):
    body = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "message": "SUCCESS",
                "fields": [
                    {"inferText": "촬영한", "inferConfidence": 0.99, "lineBreak": False},
                    {"inferText": "감명", "inferConfidence": 0.98, "lineBreak": False},
                    {"inferText": "구절", "inferConfidence": 0.97, "lineBreak": False},
                    {"inferText": "이미지를", "inferConfidence": 0.96, "lineBreak": False},
                    {"inferText": "텍스트로", "inferConfidence": 0.95, "lineBreak": True},
                ],
            }
        ]
    }
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    assert result.lines == ["촬영한 감명 구절 이미지를 텍스트로"]
    assert result.text == "촬영한 감명 구절 이미지를 텍스트로"


def test_multiple_lines_are_separated_by_newline(monkeypatch):
    body = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "message": "SUCCESS",
                "fields": [
                    {"inferText": "첫", "inferConfidence": 0.99, "lineBreak": False},
                    {"inferText": "번째", "inferConfidence": 0.98, "lineBreak": False},
                    {"inferText": "줄", "inferConfidence": 0.97, "lineBreak": True},
                    {"inferText": "두", "inferConfidence": 0.96, "lineBreak": False},
                    {"inferText": "번째", "inferConfidence": 0.95, "lineBreak": False},
                    {"inferText": "줄", "inferConfidence": 0.94, "lineBreak": True},
                ],
            }
        ]
    }
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    assert result.lines == ["첫 번째 줄", "두 번째 줄"]
    assert result.text == "첫 번째 줄\n두 번째 줄"


def test_empty_infer_text_is_ignored(monkeypatch):
    body = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "message": "SUCCESS",
                "fields": [
                    {"inferText": "촬영한", "inferConfidence": 0.99, "lineBreak": False},
                    {"inferText": "", "inferConfidence": 0.98, "lineBreak": False},
                    {"inferText": "구절", "inferConfidence": 0.97, "lineBreak": True},
                ],
            }
        ]
    }
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    assert result.lines == ["촬영한 구절"]
    assert result.text == "촬영한 구절"


def test_last_field_without_line_break_is_flushed_as_last_line(monkeypatch):
    body = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "message": "SUCCESS",
                "fields": [
                    {"inferText": "첫", "inferConfidence": 0.99, "lineBreak": True},
                    {"inferText": "마지막", "inferConfidence": 0.98, "lineBreak": False},
                    {"inferText": "줄", "inferConfidence": 0.97, "lineBreak": False},
                ],
            }
        ]
    }
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    assert result.lines == ["첫", "마지막 줄"]
    assert result.text == "첫\n마지막 줄"


def test_confidence_is_average_of_field_confidences(monkeypatch):
    _install_fake_client(monkeypatch, response=_FakeResponse(200, SUCCESS_BODY))

    result = _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))

    assert result.confidence == pytest.approx((0.99 + 0.97 + 0.95) / 3, rel=1e-4)


def test_empty_fields_raises_empty_result_error(monkeypatch):
    body = {"images": [{"inferResult": "SUCCESS", "message": "SUCCESS", "fields": []}]}
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    with pytest.raises(clova_ocr.ClovaOcrEmptyResultError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_infer_result_failure_raises_recognition_failed_error(monkeypatch):
    body = {"images": [{"inferResult": "FAILURE", "message": "이미지 인식 실패"}]}
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    with pytest.raises(clova_ocr.ClovaOcrRecognitionFailedError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_missing_images_field_raises_request_failed_error(monkeypatch):
    _install_fake_client(monkeypatch, response=_FakeResponse(200, {}))

    with pytest.raises(clova_ocr.ClovaOcrRequestFailedError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_invalid_json_raises_request_failed_error(monkeypatch):
    _install_fake_client(
        monkeypatch, response=_FakeResponse(200, payload=None, json_error=True)
    )

    with pytest.raises(clova_ocr.ClovaOcrRequestFailedError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_non_200_status_raises_request_failed_error(monkeypatch):
    _install_fake_client(monkeypatch, response=_FakeResponse(500, {}))

    with pytest.raises(clova_ocr.ClovaOcrRequestFailedError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_http_error_raises_request_failed_error(monkeypatch):
    _install_fake_client(monkeypatch, exception=httpx.ConnectError("connection failed"))

    with pytest.raises(clova_ocr.ClovaOcrRequestFailedError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_timeout_raises_clova_ocr_timeout_error(monkeypatch):
    _install_fake_client(monkeypatch, exception=httpx.TimeoutException("timed out"))

    with pytest.raises(clova_ocr.ClovaOcrTimeoutError):
        _run(clova_ocr.extract_text_from_image(b"bytes", "jpg"))


def test_diagnostic_logs_do_not_leak_secret_or_url_or_body(monkeypatch, caplog):
    """진단 로그에 Secret/Invoke URL/base64 데이터/raw body가 노출되지 않는지 확인한다."""
    body = {"images": [{"inferResult": "FAILURE", "message": "실패"}]}
    _install_fake_client(monkeypatch, response=_FakeResponse(200, body))

    with caplog.at_level("INFO", logger="app.services.clova_ocr"):
        with pytest.raises(clova_ocr.ClovaOcrRecognitionFailedError):
            _run(clova_ocr.extract_text_from_image(b"fake-image-bytes", "jpg"))

    log_text = "\n".join(record.message for record in caplog.records)

    assert clova_ocr.settings.CLOVA_OCR_SECRET_KEY not in log_text
    assert clova_ocr.settings.CLOVA_OCR_INVOKE_URL not in log_text
    assert "fake-image-bytes" not in log_text
    assert base64.b64encode(b"fake-image-bytes").decode("ascii") not in log_text
    # inferResult 값만 기록되어야 하고, message 등 raw body 전체가 통째로 남지 않아야 한다.
    assert "실패" not in log_text
    assert "FAILURE" in log_text
