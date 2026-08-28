"""OCR API 요청/응답 스키마."""
from typing import Any

from pydantic import BaseModel, Field


class OcrSentencesResponse(BaseModel):
    """POST /api/v1/ocr/sentences 응답 스키마.

    CLOVA OCR의 raw 응답을 그대로 노출하지 않고, Frontend가 사용하기
    쉬운 최소한의 형태로 가공한 결과만 포함한다.
    """

    text: str = Field(description="줄바꿈으로 재구성된 전체 OCR 텍스트")
    lines: list[str] = Field(description="줄 단위 텍스트 목록")
    request_id: str = Field(description="내부 추적용 OCR 요청 ID")
    confidence: float | None = Field(
        default=None, description="인식 신뢰도 (0~1 범위)"
    )
    language: str | None = Field(
        default=None, description="인식된 주요 언어 ('ko', 'en', 'ja', 'zh', 'mixed')"
    )
    provider: str = Field(default="bedrock", description="사용한 OCR 공급자")


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
    lines: list[str] = Field(description="인식된 줄 단위 텍스트 목록")
    request_id: str = Field(description="내부 추적용 OCR 요청 ID")
    confidence: float | None = Field(
        default=None,
        description=(
            "인식 신뢰도. AWS Bedrock Qwen3-VL은 공식 OCR confidence를 "
            "제공하지 않으므로 항상 None을 반환한다."
        ),
    )
    isbn: str | None = Field(
        default=None,
        description="표지에서 인식한 ISBN (하이픈·공백 제거된 숫자 문자열). 없으면 None",
    )
    book_id: Any = Field(
        default=None,
        description="backend-book 서재에 등록된 책의 ID (POST /api/v1/library/books 결과)",
    )
    already_registered: bool = Field(
        default=False,
        description=(
            "인식한 ISBN이 이미 사용자의 서재에 등록되어 있었으면 true. "
            "이 경우 새로 등록하지 않고 기존 book_id를 반환한다."
        ),
    )
    book: dict[str, Any] | None = Field(
        default=None,
        description=(
            "backend-book /search에서 조회한 도서 정보. 서재에 이미 있으면 저장된 "
            "도서 데이터, 알라딘에서 찾았으면 외부 조회 결과다. 어디에도 없으면 None "
            "(OCR 후보로 폴백 등록)."
        ),
    )
