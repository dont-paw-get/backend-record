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


class OcrCoverResponse(BaseModel):
    """POST /api/v1/ocr/covers 응답 스키마.

    책 표지 OCR만으로는 제목/저자를 100% 확정할 수 없으므로, 확정값이
    아닌 "후보"로 응답한다. 추출 근거(글자 크기, 저자 표기 키워드 등)가
    부족하면 title_candidate는 None, author_candidates는 빈 배열이 될 수
    있다. 최종 확정은 Frontend에서 사용자 확인을 거쳐야 한다.
    """

    title_candidate: str | None = Field(
        default=None, description="표지에서 가장 큰 글씨로 인식된 줄 (제목 후보)"
    )
    author_candidates: list[str] = Field(
        default_factory=list,
        description="'지음/글/옮김' 등 저자 표기 키워드가 포함된 줄 목록 (저자 후보)",
    )
    lines: list[str] = Field(description="lineBreak 기준으로 재구성된 줄 단위 텍스트 목록")
    request_id: str = Field(description="내부 추적용 CLOVA OCR 요청 ID")
    confidence: float | None = Field(
        default=None, description="필드별 인식 신뢰도의 평균값 (0~1)"
    )
