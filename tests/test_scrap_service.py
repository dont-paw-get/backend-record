"""app/services/scrap_service.py 단위 테스트.

ScrapRepository.create는 add/flush까지만 수행하므로, Service가
transaction 경계(commit/rollback)를 올바르게 제어하는지를 Session을
mock으로 대체해 검증한다. 실제 PostgreSQL 연결은 사용하지 않는다.
"""
from unittest.mock import MagicMock

import pytest

from app.schemas.scrap import ScrapCreateRequest
from app.services.scrap_service import ScrapCreationError, ScrapService


def _make_service():
    mock_session = MagicMock()
    service = ScrapService(mock_session)
    return service, mock_session


def _make_request(**overrides):
    data = {
        "book_id": 10,
        "sentence": "우리는 우리가 읽은 것으로 만들어진다.",
        "page_number": 132,
        "scrap_image_url": "https://example.com/scraps/abc.jpg",
        "memo": "기억하고 싶은 문장",
    }
    data.update(overrides)
    return ScrapCreateRequest(**data)


def test_create_scrap_builds_scrap_with_request_values():
    service, mock_session = _make_service()
    request = _make_request()

    result = service.create_scrap(request)

    assert result.book_id == request.book_id
    assert result.sentence == request.sentence
    assert result.page_number == request.page_number
    assert result.scrap_image_url == request.scrap_image_url
    assert result.memo == request.memo


def test_create_scrap_allows_missing_page_number_and_memo():
    service, mock_session = _make_service()
    request = _make_request(page_number=None, memo=None)

    result = service.create_scrap(request)

    assert result.page_number is None
    assert result.memo is None


def test_create_scrap_commits_and_refreshes_on_success():
    service, mock_session = _make_service()
    request = _make_request()

    service.create_scrap(request)

    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once()
    mock_session.rollback.assert_not_called()


def test_create_scrap_rolls_back_and_raises_on_db_error():
    service, mock_session = _make_service()
    mock_session.flush.side_effect = RuntimeError("db connection lost")
    request = _make_request()

    with pytest.raises(ScrapCreationError):
        service.create_scrap(request)

    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_not_called()


def test_create_scrap_rolls_back_and_raises_when_commit_fails():
    service, mock_session = _make_service()
    mock_session.commit.side_effect = RuntimeError("commit failed")
    request = _make_request()

    with pytest.raises(ScrapCreationError):
        service.create_scrap(request)

    mock_session.rollback.assert_called_once()
