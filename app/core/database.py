from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델의 베이스 클래스.

    이번 Jira(CLIAR-39)에서는 실제 도메인 모델을 만들지 않습니다.
    향후 BOOK/SCRAP 등 모델이 이 Base를 상속해 정의됩니다.
    """

    pass


def get_db() -> Session:
    """FastAPI dependency로 사용할 DB 세션 제공자."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
