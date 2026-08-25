from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Scrap(Base):
    """사용자가 최종 확인한 문장 스크랩 정보.

    scrap에는 member_id를 두지 않는다. 소유권은
    scrap.book_id -> library_book -> member_id 순으로 결정되는 구조이며,
    library_book은 backend-record가 소유하지 않으므로 이 저장소에는
    library_book 모델/FK를 두지 않는다. book_id는 외부 서비스의 책
    식별자를 참조하는 값으로만 관리한다 (CLIAR-52 범위 내 결정, 후속
    Jira에서 소유권 검증 방식을 별도로 정의해야 한다).
    """

    __tablename__ = "scrap"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    book_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    sentence: Mapped[str] = mapped_column(Text, nullable=False)

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scrap_image_url: Mapped[str] = mapped_column(Text, nullable=False)

    memo: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_scrap_book_id", "book_id"),)
