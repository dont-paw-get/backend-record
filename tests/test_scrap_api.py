"""POST /api/v1/scraps API 테스트.

Service 계층(app.api.scraps.ScrapService)은 monkeypatch로 대체하여
실제 DB 접근 없이 라우터의 validation/response 매핑/에러 처리만 검증한다.
CLOVA OCR은 이 API에서 호출하지 않으므로 관련 mock도 필요하지 않다.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.scrap import Scrap
from app.services.scrap_service import ScrapCreationError

client = TestClient(app)

SCRAPS_URL = "/api/v1/scraps"

VALID_PAYLOAD = {
    "book_id": 10,
    "sentence": "우리는 우리가 읽은 것으로 만들어진다.",
    "page_number": 132,
    "scrap_image_url": "https://example.com/scraps/abc.jpg",
    "memo": "기억하고 싶은 문장",
}


def _fake_saved_scrap(**overrides):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = {
        "id": 1,
        "book_id": 10,
        "sentence": "우리는 우리가 읽은 것으로 만들어진다.",
        "page_number": 132,
        "scrap_image_url": "https://example.com/scraps/abc.jpg",
        "memo": "기억하고 싶은 문장",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return Scrap(**data)


def test_create_scrap_with_all_fields_returns_201_and_saved_values(monkeypatch):
    def fake_create_scrap(self, request):
        assert request.book_id == VALID_PAYLOAD["book_id"]
        assert request.sentence == VALID_PAYLOAD["sentence"]
        assert request.page_number == VALID_PAYLOAD["page_number"]
        assert request.scrap_image_url == VALID_PAYLOAD["scrap_image_url"]
        assert request.memo == VALID_PAYLOAD["memo"]
        return _fake_saved_scrap()

    monkeypatch.setattr(
        "app.api.scraps.ScrapService.create_scrap", fake_create_scrap
    )

    response = client.post(SCRAPS_URL, json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["book_id"] == VALID_PAYLOAD["book_id"]
    assert body["sentence"] == VALID_PAYLOAD["sentence"]
    assert body["page_number"] == VALID_PAYLOAD["page_number"]
    assert body["scrap_image_url"] == VALID_PAYLOAD["scrap_image_url"]
    assert body["memo"] == VALID_PAYLOAD["memo"]
    assert "created_at" in body
    assert "updated_at" in body


def test_create_scrap_without_page_number_succeeds(monkeypatch):
    def fake_create_scrap(self, request):
        assert request.page_number is None
        return _fake_saved_scrap(page_number=None)

    monkeypatch.setattr(
        "app.api.scraps.ScrapService.create_scrap", fake_create_scrap
    )

    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "page_number"}
    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 201
    assert response.json()["page_number"] is None


def test_create_scrap_without_memo_succeeds(monkeypatch):
    def fake_create_scrap(self, request):
        assert request.memo is None
        return _fake_saved_scrap(memo=None)

    monkeypatch.setattr(
        "app.api.scraps.ScrapService.create_scrap", fake_create_scrap
    )

    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "memo"}
    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 201
    assert response.json()["memo"] is None


def test_create_scrap_without_page_number_and_memo_succeeds(monkeypatch):
    def fake_create_scrap(self, request):
        assert request.page_number is None
        assert request.memo is None
        return _fake_saved_scrap(page_number=None, memo=None)

    monkeypatch.setattr(
        "app.api.scraps.ScrapService.create_scrap", fake_create_scrap
    )

    payload = {
        k: v for k, v in VALID_PAYLOAD.items() if k not in ("page_number", "memo")
    }
    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 201


def test_create_scrap_missing_sentence_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "sentence"}

    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 422


def test_create_scrap_missing_book_id_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "book_id"}

    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 422


def test_create_scrap_missing_scrap_image_url_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "scrap_image_url"}

    response = client.post(SCRAPS_URL, json=payload)

    assert response.status_code == 422


def test_create_scrap_service_error_returns_500_without_leaking_detail(monkeypatch):
    def fake_create_scrap(self, request):
        raise ScrapCreationError("DB connection lost: password=secret")

    monkeypatch.setattr(
        "app.api.scraps.ScrapService.create_scrap", fake_create_scrap
    )

    response = client.post(SCRAPS_URL, json=VALID_PAYLOAD)

    assert response.status_code == 500
    assert "password" not in response.text
    assert "secret" not in response.text
