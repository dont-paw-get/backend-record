"""Scrap 엔티티에 대한 순수 DB 접근 계층.

이 Repository는 SQLAlchemy Session을 통한 최소한의 DB 접근 책임만
가진다. HTTP 예외 처리, FastAPI Request/Response, 인증/인가, OCR,
S3 등 다른 계층의 책임은 이 모듈에 포함하지 않는다.

Transaction 경계(commit/rollback)는 이 Repository가 아니라 상위
Service 계층이 제어한다. 그래야 향후 Service가 여러 Repository 호출을
하나의 transaction으로 묶거나, 실패 시 rollback을 일관되게 처리할 수
있다. 따라서 이 Repository는 commit을 직접 호출하지 않고 add/flush까지만
수행한다.
"""
from sqlalchemy.orm import Session

from app.models.scrap import Scrap


class ScrapRepository:
    """Scrap 엔티티에 대한 최소 DB 접근을 담당하는 Repository.

    CLIAR-52 범위는 model/repository 기반 마련이며, 생성 API 등 실제
    엔드포인트는 포함하지 않는다. 따라서 이 Repository도 생성(add)과
    단건 조회(get_by_id)까지만 제공하고, CLIAR-52 범위를 넘는 조회/수정/
    삭제 CRUD는 실제로 필요한 Jira에서 추가한다.
    """

    def __init__(self, session: Session):
        self._session = session

    def create(self, scrap: Scrap) -> Scrap:
        """새로운 Scrap을 session에 추가하고 flush한다.

        commit은 호출하지 않는다. transaction 확정 여부는 이 메서드를
        호출하는 Service 계층이 결정한다.
        """
        self._session.add(scrap)
        self._session.flush()
        return scrap

    def get_by_id(self, scrap_id: int) -> Scrap | None:
        """id로 Scrap 단건을 조회한다. 없으면 None을 반환한다.

        주의: 이 메서드는 현재 deleted_at(논리 삭제) 여부를 필터링하지
        않고 그대로 반환한다. 논리 삭제된 row를 조회 대상에서 제외할지
        여부는 실제 조회 API를 구현하는 후속 Jira에서 결정해야 한다.
        """
        return self._session.get(Scrap, scrap_id)
