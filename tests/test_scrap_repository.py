"""app/repositories/scrap_repository.py에 대한 단위 테스트.

주의(전제조건): SCRAP.book_id는 공용 RDS의 BOOK.book_id를 참조하는 FK이며,
backend-record는 BOOK 테이블/모델을 소유하지 않는다. 로컬 개발 PostgreSQL에는
아직 BOOK 테이블이 없어 실제 INSERT/FK 제약을 포함한 통합 테스트를 이
저장소에서 실행할 수 없다(FK 위반으로 실패한다). SQLite로 PostgreSQL의
FK/CHECK 제약을 대체해 검증하는 것도 이번 정책상 지양한다.

따라서 이 테스트는 실제 DB 대신 SQLAlchemy Session을 mock으로 대체해,
ScrapRepository가 Session의 올바른 메서드를 올바른 인자로 호출하는지
(Repository의 책임 범위)만 검증한다. 실제 PostgreSQL 대상 통합 검증은
BOOK 테이블이 준비된 이후 별도로 수행해야 한다.
"""
from unittest.mock import MagicMock

from app.models.scrap import Scrap
from app.repositories.scrap_repository import ScrapRepository


def _make_repository():
    mock_session = MagicMock()
    repository = ScrapRepository(mock_session)
    return repository, mock_session


def test_create_adds_and_flushes_scrap():
    """Repository는 commit을 직접 수행하지 않고 add/flush까지만
    담당한다. transaction 경계(commit/rollback)는 상위 Service 계층이
    제어할 수 있어야 한다."""
    repository, mock_session = _make_repository()
    scrap = Scrap(book_id=1, sentence="문장", scrap_image_url="https://example.com/a.jpg")

    result = repository.create(scrap)

    mock_session.add.assert_called_once_with(scrap)
    mock_session.flush.assert_called_once()
    mock_session.commit.assert_not_called()
    assert result is scrap


def test_get_by_id_queries_by_id():
    repository, mock_session = _make_repository()
    expected_scrap = Scrap(
        id=1, book_id=1, sentence="문장", scrap_image_url="https://example.com/a.jpg"
    )
    mock_session.get.return_value = expected_scrap

    result = repository.get_by_id(1)

    mock_session.get.assert_called_once_with(Scrap, 1)
    assert result is expected_scrap


def test_get_by_id_returns_none_when_not_found():
    repository, mock_session = _make_repository()
    mock_session.get.return_value = None

    result = repository.get_by_id(999)

    assert result is None


def test_repository_does_not_import_http_or_auth_concerns():
    """Repository 모듈이 HTTPException/FastAPI/OCR/S3/Cognito 등을
    import하지 않는지 확인한다 (책임 분리 정책 검증).

    docstring/주석까지 검사 대상에 포함하면 정책을 설명하는 문구 자체가
    거짓 실패를 유발하므로, 실제 import 구문만 대상으로 확인한다.
    """
    import ast
    import inspect

    from app.repositories import scrap_repository

    source = inspect.getsource(scrap_repository)
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_module_prefixes = ("fastapi", "boto3", "httpx")
    for module_name in imported_modules:
        assert not module_name.startswith(forbidden_module_prefixes)
