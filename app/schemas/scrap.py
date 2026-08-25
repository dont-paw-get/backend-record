"""Scrap 생성 API 요청/응답 스키마."""
from datetime import datetime

from pydantic import BaseModel, Field


class ScrapCreateRequest(BaseModel):
    """POST /api/v1/scraps 요청 스키마.

    id / created_at / updated_at / deleted_at은 클라이언트가 지정할 수
    없으며, 서버(DB)에서 자동으로 생성된다.
    """

    book_id: int = Field(description="스크랩이 속한 책의 식별자 (외부 서비스 참조 값)")
    sentence: str = Field(description="사용자가 OCR 결과를 확인/수정한 최종 문장")
    page_number: int | None = Field(default=None, description="문장이 위치한 페이지 번호")
    scrap_image_url: str = Field(description="Crop/회전이 완료된 최종 스크랩 이미지 URL")
    memo: str | None = Field(default=None, description="사용자가 남긴 메모")


class ScrapResponse(BaseModel):
    """POST /api/v1/scraps 응답 스키마."""

    id: int
    book_id: int
    sentence: str
    page_number: int | None
    scrap_image_url: str
    memo: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
