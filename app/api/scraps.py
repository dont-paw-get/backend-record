"""문장 스크랩 생성 API.

사용자가 CLOVA OCR 결과를 확인하고 최종 수정한 문장(sentence)과 이미
업로드된 스크랩 이미지 URL(scrap_image_url)을 받아 DB에 저장한다.
이 API는 OCR을 재호출하지 않으며, 이미지 업로드도 수행하지 않는다.

현재 backend-record는 library_book 모델이나 backend-book API 연동을
가지고 있지 않으므로, book_id가 실제 존재하는 책인지 또는 요청 사용자가
소유한 책인지에 대한 검증은 이번 범위에서 수행하지 않는다 (후속 Jira
필요사항).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.scrap import ScrapCreateRequest, ScrapResponse
from app.services.scrap_service import ScrapCreationError, ScrapService

router = APIRouter(prefix="/api/v1/scraps", tags=["scraps"])


@router.post("", response_model=ScrapResponse, status_code=status.HTTP_201_CREATED)
def create_scrap(
    request: ScrapCreateRequest, db: Session = Depends(get_db)
) -> ScrapResponse:
    """최종 확인된 문장 스크랩을 생성한다."""
    service = ScrapService(db)

    try:
        scrap = service.create_scrap(request)
    except ScrapCreationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="스크랩 저장 중 오류가 발생했습니다.",
        )

    return ScrapResponse.model_validate(scrap)
