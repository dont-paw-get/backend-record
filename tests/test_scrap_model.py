"""app/models/scrap.py에 대한 단위 테스트.

실제 PostgreSQL 연결 없이 SQLAlchemy 모델 정의(컬럼, PK, nullable,
timestamp default, deleted_at, index 등)만 ERD 기준으로 검증한다.

SCRAP.book_id는 backend-record가 소유하지 않는 library_book(외부 서비스)의
식별자를 참조하는 값이다. library_book 모델/FK를 이 저장소에 만들지
않으므로 book_id는 FK 없는 일반 컬럼으로만 존재해야 한다.
"""
from sqlalchemy import BigInteger, DateTime, Text

from app.models.scrap import Scrap


def _column(name):
    return Scrap.__table__.columns[name]


def test_scrap_table_has_expected_columns():
    expected_columns = {
        "id",
        "book_id",
        "sentence",
        "page_number",
        "scrap_image_url",
        "memo",
        "created_at",
        "updated_at",
        "deleted_at",
    }

    actual_columns = set(Scrap.__table__.columns.keys())

    assert expected_columns.issubset(actual_columns)


def test_table_name_is_scrap():
    assert Scrap.__tablename__ == "scrap"


def test_id_is_primary_key_bigint_autoincrement():
    column = _column("id")

    assert column.primary_key is True
    assert isinstance(column.type, BigInteger)
    assert column.autoincrement in (True, "auto")


def test_book_id_is_bigint_not_null_without_foreign_key():
    column = _column("book_id")

    assert isinstance(column.type, BigInteger)
    assert column.nullable is False
    # library_book 모델/FK를 이 저장소에서 만들지 않으므로 book_id는
    # 외부 식별자 참조 값으로만 존재해야 한다 (FK 없음).
    assert len(column.foreign_keys) == 0


def test_sentence_is_text_not_null():
    column = _column("sentence")

    assert isinstance(column.type, Text)
    assert column.nullable is False


def test_scrap_image_url_is_text_not_null():
    column = _column("scrap_image_url")

    assert isinstance(column.type, Text)
    assert column.nullable is False


def test_optional_columns_are_nullable():
    assert _column("page_number").nullable is True
    assert _column("memo").nullable is True
    assert _column("deleted_at").nullable is True


def test_forbidden_columns_do_not_exist():
    """member_id / user_id 등은 정책상 SCRAP 테이블에 존재하지 않아야
    한다. 소유권은 scrap.book_id -> library_book -> member_id로 결정한다."""
    forbidden = {"member_id", "user_id", "source_image_url", "original_image_url"}

    actual_columns = set(Scrap.__table__.columns.keys())

    assert forbidden.isdisjoint(actual_columns)


def test_created_at_and_updated_at_are_timezone_aware_and_not_nullable():
    created_at = _column("created_at")
    updated_at = _column("updated_at")

    assert isinstance(created_at.type, DateTime)
    assert created_at.type.timezone is True
    assert created_at.nullable is False

    assert isinstance(updated_at.type, DateTime)
    assert updated_at.type.timezone is True
    assert updated_at.nullable is False


def test_deleted_at_is_timezone_aware_and_nullable():
    deleted_at = _column("deleted_at")

    assert isinstance(deleted_at.type, DateTime)
    assert deleted_at.type.timezone is True
    assert deleted_at.nullable is True


def test_index_on_book_id_exists():
    index_names = {index.name for index in Scrap.__table__.indexes}

    assert "ix_scrap_book_id" in index_names

    matching_index = next(
        index for index in Scrap.__table__.indexes if index.name == "ix_scrap_book_id"
    )
    indexed_column_names = [col.name for col in matching_index.columns]
    assert indexed_column_names == ["book_id"]
