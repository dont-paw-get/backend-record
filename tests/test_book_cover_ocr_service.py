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


# --- 짧은 저자 marker("저", "역", "글")의 substring 오탐 방지 테스트 (CLIAR-136) ---


@pytest.mark.parametrize(
    "author_line",
    [
        "김영하 지음",
        "이수진 지음",
        "한강 저",
        "홍길동 옮김",
        "김철수 편저",
        "박작가 글",
        "이번역 역",
    ],
)
def test_valid_author_marker_lines_are_recognized(monkeypatch, author_line):
    """실제 저자/역자 표기로 사용된 줄은 그대로 저자 후보로 인식되어야 한다."""
    fields = [
        _field("책 제목", 0, 100, True),
        _field(author_line, 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert result.author_candidates == [author_line]


@pytest.mark.parametrize(
    "non_author_line",
    [
        "저장한 스크랩 문장 편집",
        "저장한 스크랩 문장 삭제",
        "저장한 문장",
        "저장한 스크랩",
        "역사 이야기",
        "역량 강화",
        "글자가 큽니다",
        "글쓰기 방법",
    ],
)
def test_lines_with_short_marker_as_substring_are_not_false_positives(
    monkeypatch, non_author_line
):
    """짧은 marker("저", "역", "글")가 일반 단어 내부에 포함된 줄은
    저자 후보로 잘못 인식되면 안 된다 (CLIAR-136 회귀 재현)."""
    fields = [
        _field("책 제목", 0, 100, True),
        _field(non_author_line, 150, 170, True),
    ]
    _install_fake_client(monkeypatch, _success_body(fields))

    result = _run(clova_ocr.extract_book_cover_candidates(b"bytes", "jpg"))

    assert non_author_line not in result.author_candidates


def test_ocr_test_png_reproduction_case_has_no_false_positive_author_candidates(monkeypatch):
    """dev에서 실제로 재현된 ocr-test.png 케이스: 스크랩 문장들이 저자 후보로
    잘못 추출되지 않아야 한다."""
    lines_text = [
        "촬영한 감명 구절 이미지를 텍스트로",
        "변환/수정된 문장을 책·페이지와 함께",
        "특정 책의 스크랩 문장 모아보기",
        "저장한 스크랩 문장 편집",
        "저장한 스크랩 문장 삭제",
    ]
    fields = [_field(line, 0, 50, True) for line in lines_text]
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
