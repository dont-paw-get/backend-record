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


def test_settings_requires_database_url(monkeypatch):
    """DATABASE_URL에 기본값이 없으므로, 값이 없으면 설정 로딩이 실패해야 한다.

    로컬 실제 .env 파일에 DATABASE_URL이 설정되어 있어도 이 테스트가
    영향받지 않도록, OS 환경변수만 제거하는 것에 더해 Settings 생성 시
    _env_file=None으로 .env 파일 로딩 자체를 명시적으로 비활성화한다.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("app.core.config", None)

    config_module = importlib.import_module("app.core.config")

    with pytest.raises(ValidationError):
        config_module.Settings(_env_file=None)


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
