"""POST /api/v1/ocr/sentences API 테스트.

CLOVA OCR 호출부(app.api.ocr.extract_text_from_image)는 monkeypatch로
대체하여 실제 외부 호출 없이 라우터의 파일 검증/에러 매핑/응답 형태만
검증한다.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.services import bedrock_ocr, clova_ocr

client = TestClient(app)

OCR_URL = "/api/v1/ocr/sentences"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024


def _fake_result():
    return clova_ocr.ClovaOcrResult(
        text="첫 번째 줄\n두 번째 줄",
        lines=["첫 번째 줄", "두 번째 줄"],
        request_id="11111111-1111-1111-1111-111111111111",
        confidence=0.97,
    )


def _fake_bedrock_result():
    return bedrock_ocr.BedrockOcrResult(
        text="베드락 첫 번째 줄\n베드락 두 번째 줄",
        lines=["베드락 첫 번째 줄", "베드락 두 번째 줄"],
        request_id="22222222-2222-2222-2222-222222222222",
        confidence=None,
    )


def test_ocr_sentences_accepts_jpeg_and_returns_text_and_lines(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        assert image_format == "jpg"
        return _fake_result()

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "첫 번째 줄\n두 번째 줄"
    assert body["lines"] == ["첫 번째 줄", "두 번째 줄"]
    assert body["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["confidence"] == 0.97
    assert body["provider"] == "clova"


def test_ocr_sentences_accepts_png(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        assert image_format == "png"
        return _fake_result()

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.png", b"fake-bytes", PNG_CONTENT_TYPE)}
    )

    assert response.status_code == 200


def test_ocr_sentences_with_bedrock_provider(monkeypatch):
    async def fake_bedrock_extract(image_bytes, image_format, model_id=None):
        assert image_format == "jpg"
        assert model_id == "qwen.qwen3-vl-235b-a22b"
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_bedrock_extract)

    response = client.post(
        f"{OCR_URL}?provider=bedrock&model_id=qwen.qwen3-vl-235b-a22b",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "베드락 첫 번째 줄\n베드락 두 번째 줄"
    assert body["lines"] == ["베드락 첫 번째 줄", "베드락 두 번째 줄"]
    assert body["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["confidence"] is None
    assert body["provider"] == "bedrock"


def test_ocr_sentences_rejects_empty_file():
    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 400


def test_ocr_sentences_rejects_unsupported_content_type():
    response = client.post(
        OCR_URL, files={"image": ("sentence.gif", b"fake-bytes", "image/gif")}
    )

    assert response.status_code == 415


def test_ocr_sentences_rejects_oversized_file():
    oversized = b"0" * (MAX_IMAGE_SIZE_BYTES + 1)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", oversized, JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 413


def test_ocr_sentences_maps_timeout_error_to_504(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrTimeoutError("timeout")

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 504


def test_ocr_sentences_maps_bedrock_timeout_error_to_504(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrTimeoutError("timeout")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?provider=bedrock",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
    )

    assert response.status_code == 504


def test_ocr_sentences_maps_request_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrRequestFailedError("boom")

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 502


def test_ocr_sentences_maps_bedrock_request_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrRequestFailedError("boom")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?provider=bedrock",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
    )

    assert response.status_code == 502


def test_ocr_sentences_maps_recognition_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrRecognitionFailedError("boom")

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 502


def test_ocr_sentences_maps_empty_result_error_to_422(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrEmptyResultError("empty")

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 422


def test_ocr_sentences_maps_bedrock_empty_result_error_to_422(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrEmptyResultError("empty")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?provider=bedrock",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
    )

    assert response.status_code == 422


def test_ocr_sentences_error_response_does_not_leak_upstream_message(monkeypatch):
    secret_like_message = "CLOVA_OCR_SECRET_KEY=super-secret-value"

    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrRequestFailedError(secret_like_message)

    monkeypatch.setattr(clova_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert secret_like_message not in response.text
