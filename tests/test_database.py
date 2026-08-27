"""app/core/database.py 및 DATABASE_URL 설정에 대한 단위 테스트.

이번 Jira(CLIAR-39)에서는 실제 PostgreSQL 연결 없이 검증 가능한
설정/구조 수준의 테스트만 다룹니다. 실제 PostgreSQL 연결 검증은
로컬 Docker 환경에서 사용자가 별도로 수행합니다.
"""
import importlib
import sys
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import DeclarativeBase, Session

TEST_DATABASE_URL = (
    "postgresql+psycopg://test_user:test_password@localhost:5433/test_db"
)


def _reload_with_database_url(monkeypatch, database_url: str = TEST_DATABASE_URL):
    """DATABASE_URL을 명시적으로 주입한 뒤 config/database 모듈을 새로 로드한다.

    Settings.DATABASE_URL은 필수 값이며 기본값이 없으므로, 실제 사용자
    .env 파일에 의존하지 않고 테스트에서 직접 환경변수를 주입해야 한다.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    sys.modules.pop("app.core.database", None)
    sys.modules.pop("app.core.config", None)

    config_module = importlib.import_module("app.core.config")
    database_module = importlib.import_module("app.core.database")
    return config_module, database_module


def test_settings_reads_database_url_from_env(monkeypatch):
    config_module, _ = _reload_with_database_url(monkeypatch)

    assert config_module.settings.DATABASE_URL == TEST_DATABASE_URL


def test_database_url_defaults_to_none_when_absent(monkeypatch):
    """CLIAR-123: backend-record는 더 이상 DB 배포 의존성을 필수로 갖지 않는다.

    DATABASE_URL은 더 이상 기본값 없는 필수 필드가 아니며, 값이 없으면
    None으로 기본 동작해야 한다. 이 덕분에 DB 환경변수가 전혀 없는
    배포 환경에서도 app.main import/startup이 실패하지 않는다.

    app/core/config.py에는 module-level `settings = Settings()`가 있어
    모듈 import 시점에 곧바로 검증이 수행된다. 먼저 TEST_DATABASE_URL을
    주입한 상태로 모듈을 import해 module-level 초기화를 통과시킨 뒤,
    DATABASE_URL을 제거하고 _env_file=None으로 .env 로딩을 비활성화한
    채 Settings()를 직접 호출해도 예외 없이 생성되고 DATABASE_URL이
    None인지 확인한다.
    """
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    sys.modules.pop("app.core.config", None)
    config_module = importlib.import_module("app.core.config")

    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings_without_db = config_module.Settings(_env_file=None)
    assert settings_without_db.DATABASE_URL is None


def test_database_module_exposes_expected_objects(monkeypatch):
    _, database_module = _reload_with_database_url(monkeypatch)

    assert hasattr(database_module, "engine")
    assert hasattr(database_module, "SessionLocal")
    assert hasattr(database_module, "Base")
    assert hasattr(database_module, "get_db")


def test_base_is_declarative_base(monkeypatch):
    _, database_module = _reload_with_database_url(monkeypatch)

    assert issubclass(database_module.Base, DeclarativeBase)


def test_sessionlocal_creates_session_instance(monkeypatch):
    _, database_module = _reload_with_database_url(monkeypatch)

    session = database_module.SessionLocal()
    try:
        assert isinstance(session, Session)
    finally:
        session.close()


def test_get_db_yields_session_and_closes_it(monkeypatch):
    _, database_module = _reload_with_database_url(monkeypatch)

    mock_session = MagicMock(spec=Session)
    monkeypatch.setattr(database_module, "SessionLocal", lambda: mock_session)

    generator = database_module.get_db()
    yielded_session = next(generator)
    assert yielded_session is mock_session
    mock_session.close.assert_not_called()

    with pytest.raises(StopIteration):
        next(generator)

    mock_session.close.assert_called_once()
