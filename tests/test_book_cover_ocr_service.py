"""app/services/clova_ocr.py의 책 표지 OCR 후처리(extract_book_cover_candidates) 테스트.

sentence OCR과 동일한 CLOVA HTTP 호출 코드를 재사용하되, boundingPoly
좌표를 이용해 제목/저자 "후보"를 추출하는 로직만 검증한다. 실제 CLOVA
OCR API는 호출하지 않는다.
"""
import asyncio

import pytest

from app.services import clova_ocr


def _field(text, y_top, y_bottom, line_break, confidence=0.95):
    """bounding box 높이(y_bottom - y_top)를 가진 CLOVA field를 만든다."""
    return {
        "inferText": text,
        "inferConfidence": confidence,
        "lineBreak": line_break,
        "boundingPoly": {
            "vertices": [
                {"x": 10, "y": y_top},
                {"x": 200, "y": y_top},
                {"x": 200, "y": y_bottom},
                {"x": 10, "y": y_bottom},
            ]
        },
    }


def _success_body(fields):
    return {
        "images": [
            {"inferResult": "SUCCESS", "message": "SUCCESS", "fields": fields}
        ]
    }


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        return self.response


def _install_fake_client(monkeypatch, body):
    client = _FakeAsyncClient(_FakeResponse(200, body))
    monkeypatch.setattr(clova_ocr.httpx, "AsyncClient", lambda *a, **kw: client)


def _run(coro):
    return asyncio.run(coro)


def test_largest_line_is_returned_as_title_candidate(monkeypatch):
    """제목은 표지에서 가장 큰 글씨로 인쇄되는 경우가 많으므로, bounding box
    높이가 가장 큰 줄을 제목 후보로 삼는다."""
    fields = [
        # 제목: 큰 글씨 (높이 100)
        _field("어떤 책의", 0, 100, False),
        _field("제목입니다", 0, 100, True),
        # 저자: 작은 글씨 (높이 20)
        _field("김작가", 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.title_candidate == "어떤 책의 제목입니다"


def test_line_with_author_marker_is_returned_as_author_candidate(monkeypatch):
    """지음/글/옮김 등 저자 표기 키워드가 포함된 줄을 저자 후보로 삼는다."""
    fields = [
        _field("어떤 책의 제목", 0, 100, True),
        _field("김작가", 150, 170, False),
        _field("지음", 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.author_candidates == ["김작가 지음"]


def test_multiple_author_marker_lines_are_all_returned(monkeypatch):
    """공동 저자/역자처럼 저자 표기 키워드를 포함한 줄이 여러 개면 전부 후보로 반환한다."""
    fields = [
        _field("책 제목", 0, 100, True),
        _field("김작가", 150, 170, False),
        _field("지음", 150, 170, True),
        _field("박옮김", 200, 220, False),
        _field("옮김", 200, 220, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.author_candidates == ["김작가 지음", "박옮김 옮김"]


def test_no_author_marker_returns_empty_author_candidates(monkeypatch):
    """저자 표기 키워드를 가진 줄이 없으면 억지로 추측하지 않고 빈 목록을 반환한다."""
    fields = [
        _field("책 제목", 0, 100, True),
        _field("알 수 없는 줄", 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.author_candidates == []


def test_missing_bounding_box_info_returns_none_title_candidate(monkeypatch):
    """boundingPoly 정보가 전혀 없으면 글자 크기를 알 수 없으므로 제목 후보를
    억지로 추측하지 않고 None을 반환한다."""
    fields = [
        {"inferText": "책 제목", "inferConfidence": 0.9, "lineBreak": True},
        {"inferText": "김작가", "inferConfidence": 0.9, "lineBreak": True},
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.title_candidate is None


def test_cover_result_includes_lines_confidence_and_request_id(monkeypatch):
    fields = [
        _field("책 제목", 0, 100, True),
        _field("김작가 지음", 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.lines == ["책 제목", "김작가 지음"]
    assert result.confidence == pytest.approx(0.95, rel=1e-4)
    assert result.request_id


def test_cover_empty_result_raises_empty_result_error(monkeypatch):
    _install_fake_client(monkeypatch, _success_body([]))

    with pytest.raises(clova_ocr.ClovaOcrEmptyResultError):
        _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))


def test_cover_infer_result_failure_raises_recognition_failed_error(monkeypatch):
    body = {"images": [{"inferResult": "FAILURE", "message": "실패"}]}
    _install_fake_client(monkeypatch, body)

    with pytest.raises(clova_ocr.ClovaOcrRecognitionFailedError):
        _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))


def test_cover_timeout_raises_timeout_error(monkeypatch):
    import httpx

    class _TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None, headers=None):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(clova_ocr.httpx, "AsyncClient", lambda *a, **kw: _TimeoutClient())

    with pytest.raises(clova_ocr.ClovaOcrTimeoutError):
        _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))


def test_cover_non_200_status_raises_request_failed_error(monkeypatch):
    client = _FakeAsyncClient(_FakeResponse(500, {}))
    monkeypatch.setattr(clova_ocr.httpx, "AsyncClient", lambda *a, **kw: client)

    with pytest.raises(clova_ocr.ClovaOcrRequestFailedError):
        _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))
