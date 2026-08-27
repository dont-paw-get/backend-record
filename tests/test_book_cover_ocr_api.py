"""POST /api/v1/ocr/covers API 테스트.

CLOVA OCR 호출부(app.api.ocr.extract_book_cover_candidates)는
monkeypatch로 대체하여 실제 외부 호출 없이 라우터의 파일 검증/에러
매핑/응답 형태만 검증한다.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.services import clova_ocr

client = TestClient(app)

COVER_URL = "/api/v1/ocr/covers"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024


def _fake_cover_result(**overrides):
    data = {
        "title_candidate": "어떤 책의 제목",
        "author_candidates": ["김작가 지음"],
        "lines": ["어떤 책의 제목", "김작가 지음"],
        "request_id": "22222222-2222-2222-2222-222222222222",
        "confidence": 0.93,
    }
    data.update(overrides)
    return clova_ocr.ClovaOcrCoverResult(**data)


def test_covers_accepts_jpeg_and_returns_title_and_author_candidates(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        assert image_format == "jpg"
        return _fake_cover_result()

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title_candidate"] == "어떤 책의 제목"
    assert body["author_candidates"] == ["김작가 지음"]
    assert body["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["confidence"] == 0.93


def test_covers_accepts_png(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        assert image_format == "png"
        return _fake_cover_result()

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.png", b"fake-bytes", PNG_CONTENT_TYPE)}
    )

    assert response.status_code == 200


def test_covers_rejects_empty_file():
    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 400


def test_covers_rejects_unsupported_content_type():
    response = client.post(
        COVER_URL, files={"image": ("cover.gif", b"fake-bytes", "image/gif")}
    )

    assert response.status_code == 415


def test_covers_rejects_oversized_file():
    oversized = b"0" * (MAX_IMAGE_SIZE_BYTES + 1)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", oversized, JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 413


def test_covers_maps_timeout_error_to_504(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrTimeoutError("timeout")

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 504


def test_covers_maps_request_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrRequestFailedError("boom")

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 502


def test_covers_maps_empty_result_error_to_422(monkeypatch):
    async def fake_extract(image_bytes, image_format):
        raise clova_ocr.ClovaOcrEmptyResultError("empty")

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 422


def test_covers_returns_null_candidates_when_extraction_is_uncertain(monkeypatch):
    """제목/저자 후보를 추출하기 어려운 경우 억지로 값을 만들지 않고 null/빈 배열을 반환한다."""

    async def fake_extract(image_bytes, image_format):
        return _fake_cover_result(title_candidate=None, author_candidates=[])

    monkeypatch.setattr("app.api.ocr.extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title_candidate"] is None
    assert body["author_candidates"] == []
