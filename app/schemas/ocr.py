from typing import Any
from pydantic import BaseModel, Field

class OcrSentencesResponse(BaseModel):
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
    book_id: Any = Field(
        description="스크랩을 등록한 backend-book 서재 도서의 ID (요청으로 받은 book_id)"
    )
    scrap_id: Any | None = Field(
        default=None,
        description=(
            "backend-book에 생성된 스크랩의 ID "
            "(POST /api/v1/library/books/{bookId}/scraps 결과). "
            "RECORD-3A: save_scrap=false(OCR-only 모드)이면 backend-book 저장을 "
            "호출하지 않으므로 null이다."
        ),
    )
    scrap_image_url: str = Field(
        description=(
            "RECORD-2: OCR에 사용한 원본 이미지를 S3에 저장한 뒤 생성한 "
            "CloudFront URL. save_scrap=true이면 backend-book 스크랩 생성 요청의 "
            "scrapImageUrl로도 함께 전달된다. save_scrap=false(OCR-only)에서도 "
            "항상 채워지며, 사용자가 확인 후 별도로 스크랩을 저장할 때 사용한다."
        )
    )


class OcrCoverResponse(BaseModel):
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
