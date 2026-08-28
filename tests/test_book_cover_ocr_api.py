"""POST /api/v1/ocr/covers API 테스트.

CLIAR-143: OCR Provider가 AWS Bedrock Qwen3-VL로 전환되었다. Bedrock
호출부(app.services.bedrock_ocr.extract_book_cover_candidates)는
monkeypatch로 대체하여 실제 외부 호출 없이 라우터의 파일 검증/에러
매핑/응답 형태만 검증한다.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import bedrock_ocr

client = TestClient(app)

COVER_URL = "/api/v1/ocr/covers"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024


def _fake_cover_result(**overrides):
    data = {
        "title_candidate": "성공하는 인생의 비밀",
        "author_candidates": ["이수진 지음"],
        "lines": [
            "성공하는 인생의 비밀",
            "성공하는 사람들의 비밀을 풀어라!",
            "이수진 지음",
        ],
        "request_id": "22222222-2222-2222-2222-222222222222",
        # CLIAR-143 최종 수정: bedrock_ocr 서비스는 항상 confidence=None을
        # 반환하므로(모델이 생성한 confidence 숫자를 신뢰도로 사용하지
        # 않음), 여기서도 실제 계약과 동일하게 None을 기본값으로 둔다.
        "confidence": None,
    }
    data.update(overrides)
    return bedrock_ocr.BedrockOcrCoverResult(**data)


def test_covers_accepts_jpeg_and_returns_title_and_author_candidates(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert image_format == "jpg"
        return _fake_cover_result()

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title_candidate"] == "성공하는 인생의 비밀"
    assert body["author_candidates"] == ["이수진 지음"]
    assert body["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["confidence"] is None


def test_covers_response_confidence_is_none_even_if_model_reported_high_confidence(
    monkeypatch,
):
    """모델 응답에 confidence: 0.99가 포함되어 있어도 API 응답의 confidence는
    항상 None이어야 한다 (CLIAR-143 최종 수정, service 계층에서 이미
    None으로 정규화되므로 라우터는 그 값을 그대로 전달한다)."""
    fake_result = bedrock_ocr.BedrockOcrCoverResult(
        title_candidate="제목",
        author_candidates=["저자 지음"],
        lines=["제목", "저자 지음"],
        request_id="33333333-3333-3333-3333-333333333333",
        confidence=None,  # 실제 서비스 계층 계약: 항상 None
    )

    async def fake_extract(image_bytes, image_format, model_id=None):
        return fake_result

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    assert response.json()["confidence"] is None


def test_covers_accepts_png(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert image_format == "png"
        return _fake_cover_result()

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

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
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrTimeoutError("timeout")

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 504


def test_covers_maps_request_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrRequestFailedError("boom")

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 502


def test_covers_maps_empty_result_error_to_422(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrEmptyResultError("empty")

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 422


def test_covers_returns_null_candidates_when_extraction_is_uncertain(monkeypatch):
    """제목/저자 후보를 추출하기 어려운 경우 억지로 값을 만들지 않고 null/빈 배열을 반환한다."""

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_cover_result(
            title_candidate=None, author_candidates=[], lines=["알 수 없는 이미지"]
        )

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title_candidate"] is None
    assert body["author_candidates"] == []


def test_covers_combines_multiline_title_into_single_candidate(monkeypatch):
    """CLIAR-142에서 CLOVA bounding box heuristic으로 해결하지 못했던
    여러 줄 제목 결합 문제가, Bedrock 모델의 직접 구조화 응답으로
    해결되는지 확인한다 (실제 dev E2E 재현 표지 기준)."""

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_cover_result()

    monkeypatch.setattr(bedrock_ocr, "extract_book_cover_candidates", fake_extract)

    response = client.post(
        COVER_URL, files={"image": ("cover.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    body = response.json()
    assert body["title_candidate"] == "성공하는 인생의 비밀"
    assert "성공하는 사람들의 비밀을 풀어라!" not in body["title_candidate"]


def test_clova_ocr_module_no_longer_exists():
    """CLIAR-143: CLOVA OCR 모듈 자체가 제거되어, runtime에서 CLOVA를
    호출할 방법이 없음을 확인한다 (import 자체가 불가능)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.clova_ocr")


def test_ocr_module_only_imports_bedrock_service():
    """app.api.ocr이 bedrock_ocr만 import하고 clova 관련 모듈을 import하지
    않는지 실제 import 구문(AST)만 검사한다. docstring/주석은 검사 대상에서
    제외한다 (설명 문구에 'CLOVA'라는 단어가 등장하는 것 자체는 정상이다)."""
    import ast
    import inspect

    from app.api import ocr as ocr_module

    source = inspect.getsource(ocr_module)
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any("clova" in module_name.lower() for module_name in imported_modules)
