"""Scrap 생성에 대한 애플리케이션 로직과 transaction 경계를 담당한다.

ScrapRepository.create는 add/flush까지만 수행하고 commit을 호출하지
않는다 (CLIAR-52 설계). 따라서 이 Service가 commit/rollback을 통해
transaction을 확정하거나 되돌린다.

CLOVA OCR 재호출, OCR 결과 자동 저장, S3 업로드, book 소유권 검증 등은
이 Service의 책임이 아니다. 사용자가 이미 확인/수정한 sentence와 이미
업로드된 scrap_image_url을 그대로 저장하는 역할만 한다.
"""
from sqlalchemy.orm import Session

from app.models.scrap import Scrap
from app.repositories.scrap_repository import ScrapRepository
from app.schemas.scrap import ScrapCreateRequest


class ScrapCreationError(Exception):
    """Scrap 생성 중 DB 저장에 실패한 경우."""


class ScrapService:
    """Scrap 생성 유스케이스를 담당하는 Service 계층."""

    def __init__(self, session: Session):
        self._session = session
        self._repository = ScrapRepository(session)

    def create_scrap(self, request: ScrapCreateRequest) -> Scrap:
        """요청받은 값으로 Scrap을 생성하고 commit한다.

        DB 저장 과정(flush/commit)에서 예외가 발생하면 rollback한 뒤
        ScrapCreationError로 변환해 raise한다. 내부 DB 오류 메시지를
        그대로 노출하지 않기 위함이다.
        """
        scrap = Scrap(
            book_id=request.book_id,
            sentence=request.sentence,
            page_number=request.page_number,
            scrap_image_url=request.scrap_image_url,
            memo=request.memo,
        )

        try:
            self._repository.create(scrap)
            self._session.commit()
            self._session.refresh(scrap)
        except Exception as exc:
            self._session.rollback()
            raise ScrapCreationError("Failed to save scrap") from exc

        return scrap
