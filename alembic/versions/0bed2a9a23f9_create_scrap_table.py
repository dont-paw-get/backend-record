"""create scrap table

Revision ID: 0bed2a9a23f9
Revises: 
Create Date: 2026-08-21 11:48:59.552901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0bed2a9a23f9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # scrap.book_id는 library_book(외부 서비스가 소유)의 식별자를 참조하는
    # 값이다. library_book 모델/테이블은 backend-record가 소유하지 않으므로
    # 이 migration은 FK를 생성하지 않고 일반 컬럼 + 조회용 인덱스만 만든다.
    op.create_table(
        "scrap",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("scrap_image_url", sa.Text(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrap_book_id", "scrap", ["book_id"])


def downgrade() -> None:
    op.drop_index("ix_scrap_book_id", table_name="scrap")
    op.drop_table("scrap")
