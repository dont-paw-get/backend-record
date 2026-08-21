"""OCR API 요청/응답 스키마."""
from pydantic import BaseModel, Field


class OcrSentencesResponse(BaseModel):
    """POST /api/v1/ocr/sentences 응답 스키마.

    CLOVA OCR의 raw 응답을 그대로 노출하지 않고, Frontend가 사용하기
    쉬운 최소한의 형태로 가공한 결과만 포함한다.
    """

    text: str = Field(description="줄바꿈으로 재구성된 전체 OCR 텍스트")
    lines: list[str] = Field(description="lineBreak 기준으로 재구성된 줄 단위 텍스트 목록")
    request_id: str = Field(description="내부 추적용 CLOVA OCR 요청 ID")
    confidence: float | None = Field(
        default=None, description="필드별 인식 신뢰도의 평균값 (0~1)"
    )
