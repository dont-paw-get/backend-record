import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.auth_provider import get_access_token, get_current_member_id
from app.services import bedrock_ocr, s3_upload

client = TestClient(app)

OCR_URL = "/api/v1/ocr/sentences"
JPEG_CONTENT_TYPE = "image/jpeg"
PNG_CONTENT_TYPE = "image/png"
MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024

FAKE_MEMBER_ID = 7
FAKE_ACCESS_TOKEN = "fake-access-token"
FAKE_BOOK_ID = 42
FAKE_SCRAP_ID = 100
FAKE_OBJECT_KEY = "scraps/11111111-1111-1111-1111-111111111111.jpg"
FAKE_CLOUDFRONT_URL = s3_upload.build_cloudfront_url(FAKE_OBJECT_KEY)

# sentences 요청에 항상 함께 보내는 스크랩 대상 도서 ID.
DEFAULT_FORM = {"book_id": str(FAKE_BOOK_ID)}


@pytest.fixture(autouse=True)
def override_auth_dependencies():
    """실제 backend-auth 호출 없이 인증 의존성을 통과시킨다."""
    app.dependency_overrides[get_current_member_id] = lambda: FAKE_MEMBER_ID
    app.dependency_overrides[get_access_token] = lambda: FAKE_ACCESS_TOKEN
    yield
    app.dependency_overrides.pop(get_current_member_id, None)
    app.dependency_overrides.pop(get_access_token, None)


@pytest.fixture(autouse=True)
def stub_create_scrap(monkeypatch):
    """기본적으로 backend-book 스크랩 생성을 성공(scrap_id 반환)으로 대체한다.

    개별 테스트에서 실패 케이스를 검증할 때는 다시 monkeypatch한다.
    """
    async def fake_create_scrap(access_token, book_id, **kwargs):
        return FAKE_SCRAP_ID

    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)


@pytest.fixture(autouse=True)
def stub_s3_upload(monkeypatch):
    """기본적으로 스크랩 이미지 S3 업로드를 성공(고정 object_key 반환)으로 대체한다.

    실제 AWS S3를 호출하지 않는다. 개별 테스트에서 업로드 실패나 실제 전달된
    bytes를 검증할 때는 다시 monkeypatch한다.
    """
    async def fake_upload_scrap_image(image_bytes, content_type, client=None):
        return FAKE_OBJECT_KEY

    monkeypatch.setattr(s3_upload, "upload_scrap_image", fake_upload_scrap_image)


def _fake_bedrock_result():
    return bedrock_ocr.BedrockOcrResult(
        text="첫 번째 줄\n두 번째 줄",
        lines=["첫 번째 줄", "두 번째 줄"],
        request_id="22222222-2222-2222-2222-222222222222",
        confidence=0.97,
        language="ko",
    )


def test_ocr_sentences_accepts_jpeg_and_returns_text_and_lines(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert image_format == "jpg"
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "첫 번째 줄\n두 번째 줄"
    assert body["lines"] == ["첫 번째 줄", "두 번째 줄"]
    assert body["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["confidence"] == 0.97
    assert body["provider"] == "bedrock"
    assert body["book_id"] == FAKE_BOOK_ID
    assert body["scrap_id"] == FAKE_SCRAP_ID


def test_ocr_sentences_accepts_png(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert image_format == "png"
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.png", b"fake-bytes", PNG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200


def test_ocr_sentences_with_custom_model_id(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert model_id == "custom.qwen3-vl"
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?model_id=custom.qwen3-vl",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "bedrock"


def test_ocr_sentences_creates_scrap_with_ocr_text_and_optional_fields(monkeypatch):
    """OCR 텍스트를 sentence로, book_id/page_number/memo를 그대로 backend-book
    스크랩 생성에 전달하는지 검증한다.

    RECORD-2: scrap_image_url은 더 이상 요청 폼 값을 그대로 전달하지 않는다.
    OCR에 사용한 원본 이미지를 S3에 저장해 생성한 CloudFront URL로 항상
    대체된다(요청에 scrap_image_url을 함께 보내더라도 무시된다) - 아래
    test_ocr_sentences_generated_scrap_image_url_overrides_request_field에서
    이 대체 동작을 명시적으로 검증한다.
    """
    captured = {}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        captured["access_token"] = access_token
        captured["book_id"] = book_id
        captured.update(kwargs)
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data={
            "book_id": str(FAKE_BOOK_ID),
            "page_number": "12",
            "memo": "인상 깊은 문장",
            "scrap_image_url": "https://cdn.test.local/scrap/1.jpg",
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == FAKE_ACCESS_TOKEN
    assert captured["book_id"] == FAKE_BOOK_ID
    assert captured["sentence"] == "첫 번째 줄\n두 번째 줄"
    assert captured["page_number"] == 12
    assert captured["memo"] == "인상 깊은 문장"
    assert captured["scrap_image_url"] == FAKE_CLOUDFRONT_URL


def test_ocr_sentences_uploads_ocr_image_bytes_to_s3_once(monkeypatch):
    """OCR 성공 후 S3 uploader가 정확히 1회, OCR에 사용한 것과 동일한 image
    bytes/content_type으로 호출되는지 검증한다."""
    captured = {}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_upload(image_bytes, content_type, client=None):
        captured["call_count"] = captured.get("call_count", 0) + 1
        captured["image_bytes"] = image_bytes
        captured["content_type"] = content_type
        return FAKE_OBJECT_KEY

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr(s3_upload, "upload_scrap_image", fake_upload)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"original-image-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert captured["call_count"] == 1
    assert captured["image_bytes"] == b"original-image-bytes"
    assert captured["content_type"] == JPEG_CONTENT_TYPE


def test_ocr_sentences_generated_cloudfront_url_matches_object_key(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_upload(image_bytes, content_type, client=None):
        return "scraps/deadbeef-dead-beef-dead-deadbeefdead.png"

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr(s3_upload, "upload_scrap_image", fake_upload)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.png", b"fake-bytes", PNG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    expected_url = (
        "https://d3qnwig98jio0e.cloudfront.net/"
        "scraps/deadbeef-dead-beef-dead-deadbeefdead.png"
    )
    assert response.json()["scrap_image_url"] == expected_url
    # object_key에 이미 "scraps/"가 포함되어 있으므로 "/scraps/scraps/"로
    # 중복되지 않아야 한다.
    assert "/scraps/scraps/" not in response.json()["scrap_image_url"]


def test_ocr_sentences_generated_scrap_image_url_overrides_request_field(monkeypatch):
    """요청 폼의 scrap_image_url을 함께 보내도 backend-book에는 S3로 생성한
    CloudFront URL이 전달됨을 명시적으로 검증한다."""
    captured = {}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        captured.update(kwargs)
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data={
            **DEFAULT_FORM,
            "scrap_image_url": "https://client-supplied.example.com/should-be-ignored.jpg",
        },
    )

    assert response.status_code == 200
    assert captured["scrap_image_url"] == FAKE_CLOUDFRONT_URL
    assert captured["scrap_image_url"] != "https://client-supplied.example.com/should-be-ignored.jpg"


def test_ocr_sentences_response_includes_scrap_image_url_and_keeps_scrap_id(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scrap_image_url"] == FAKE_CLOUDFRONT_URL
    assert body["scrap_id"] == FAKE_SCRAP_ID


def test_ocr_sentences_default_param_still_auto_saves_scrap(monkeypatch):
    """save_scrap 파라미터를 전혀 보내지 않으면 기존과 동일하게 자동 저장된다."""
    create_scrap_called = {"value": False}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        create_scrap_called["value"] = True
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert create_scrap_called["value"] is True
    assert response.json()["scrap_id"] == FAKE_SCRAP_ID


def test_ocr_sentences_save_scrap_true_explicit_calls_create_scrap(monkeypatch):
    create_scrap_called = {"value": False}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        create_scrap_called["value"] = True
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        f"{OCR_URL}?save_scrap=true",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert create_scrap_called["value"] is True
    assert response.json()["scrap_id"] == FAKE_SCRAP_ID


def test_ocr_sentences_save_scrap_false_succeeds_without_calling_create_scrap(monkeypatch):
    """OCR-only 모드: OCR은 성공하지만 backend-book 스크랩 생성은 절대 호출되지 않는다."""
    create_scrap_called = {"value": False}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        create_scrap_called["value"] = True
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert create_scrap_called["value"] is False


def test_ocr_sentences_save_scrap_false_still_uploads_to_s3(monkeypatch):
    captured = {"call_count": 0}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_upload(image_bytes, content_type, client=None):
        captured["call_count"] += 1
        return FAKE_OBJECT_KEY

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr(s3_upload, "upload_scrap_image", fake_upload)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert captured["call_count"] == 1


def test_ocr_sentences_save_scrap_false_returns_cloudfront_url(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert response.json()["scrap_image_url"] == FAKE_CLOUDFRONT_URL


def test_ocr_sentences_save_scrap_false_returns_null_scrap_id(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert response.json()["scrap_id"] is None


def test_ocr_sentences_save_scrap_false_still_returns_ocr_fields(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "첫 번째 줄\n두 번째 줄"
    assert body["lines"] == ["첫 번째 줄", "두 번째 줄"]
    assert body["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["confidence"] == 0.97
    assert body["provider"] == "bedrock"
    assert body["book_id"] == FAKE_BOOK_ID


def test_ocr_sentences_save_scrap_false_accepts_png(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        assert image_format == "png"
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        f"{OCR_URL}?save_scrap=false",
        files={"image": ("sentence.png", b"fake-bytes", PNG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 200
    assert response.json()["scrap_id"] is None


def test_ocr_sentences_s3_upload_failure_does_not_call_create_scrap(monkeypatch):
    """S3 업로드가 실패하면 backend-book 스크랩 생성 API를 호출하지 않아야 한다."""
    create_scrap_called = {"value": False}

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_upload(image_bytes, content_type, client=None):
        raise s3_upload.S3UploadRequestFailedError("boom")

    async def fake_create_scrap(access_token, book_id, **kwargs):
        create_scrap_called["value"] = True
        return FAKE_SCRAP_ID

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr(s3_upload, "upload_scrap_image", fake_upload)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 502
    assert create_scrap_called["value"] is False


def test_ocr_sentences_requires_book_id(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL, files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)}
    )

    assert response.status_code == 422


def test_ocr_sentences_maps_scrap_provider_error_to_502(monkeypatch):
    from app.providers.book_provider import BookProviderError

    async def fake_extract(image_bytes, image_format, model_id=None):
        return _fake_bedrock_result()

    async def fake_create_scrap(access_token, book_id, **kwargs):
        raise BookProviderError("boom")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)
    monkeypatch.setattr("app.api.ocr.create_scrap", fake_create_scrap)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 502


def test_ocr_sentences_rejects_empty_file():
    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 400


def test_ocr_sentences_rejects_unsupported_content_type():
    response = client.post(
        OCR_URL,
        files={"image": ("sentence.gif", b"fake-bytes", "image/gif")},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 415


def test_ocr_sentences_rejects_oversized_file():
    oversized = b"0" * (MAX_IMAGE_SIZE_BYTES + 1)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", oversized, JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 413


def test_ocr_sentences_maps_timeout_error_to_504(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrTimeoutError("timeout")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 504


def test_ocr_sentences_maps_request_failed_error_to_502(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrRequestFailedError("boom")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 502


def test_ocr_sentences_maps_empty_result_error_to_422(monkeypatch):
    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrEmptyResultError("empty")

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert response.status_code == 422


def test_ocr_sentences_error_response_does_not_leak_upstream_message(monkeypatch):
    secret_like_message = "AWS_SECRET_ACCESS_KEY=super-secret-value"

    async def fake_extract(image_bytes, image_format, model_id=None):
        raise bedrock_ocr.BedrockOcrRequestFailedError(secret_like_message)

    monkeypatch.setattr(bedrock_ocr, "extract_text_from_image", fake_extract)

    response = client.post(
        OCR_URL,
        files={"image": ("sentence.jpg", b"fake-bytes", JPEG_CONTENT_TYPE)},
        data=DEFAULT_FORM,
    )

    assert secret_like_message not in response.text


def test_clova_ocr_module_no_longer_exists():
    """CLIAR-143: CLOVA OCR 모듈 자체가 제거되어, runtime에서 CLOVA를
    호출할 방법이 없음을 확인한다 (import 자체가 불가능)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.clova_ocr")


def test_ocr_sentences_only_imports_bedrock_service():
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
