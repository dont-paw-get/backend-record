# backend-record
유저 개인의 문장 수집 및 독서 감상 기록 스크랩 관리 서버

## 개발환경 준비

### 1. Python 가상환경 생성 및 활성화

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. 의존성 설치

```powershell
pip install -r requirements.txt
```

### 3. 환경변수 설정

`.env.example` 파일을 복사해 `.env` 파일을 생성하고 필요한 값을 채워주세요.
`.env` 파일은 Git에 포함되지 않습니다.

```powershell
Copy-Item .env.example .env
```

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `APP_ENV` | 실행 환경 구분 | `local` |
| `APP_HOST` | 서버 바인딩 호스트 | `0.0.0.0` |
| `APP_PORT` | 서버 포트 | `8000` |

### 4. FastAPI 애플리케이션 실행

```powershell
uvicorn app.main:app --reload
```

### 5. GET /health 확인

서버 실행 후 아래 주소로 접속하면 정상 동작 여부를 확인할 수 있습니다.

```
GET http://127.0.0.1:8000/health
```

정상 응답:

```json
{
  "status": "ok"
}
```

### 6. 테스트 실행

```powershell
pytest
```

## PostgreSQL 및 Alembic 개발환경 (CLIAR-39)

backend-record는 SQLAlchemy + Alembic + PostgreSQL 기반으로 데이터를 관리합니다.
로컬 개발 환경에서는 backend-auth의 PostgreSQL(`localhost:5432`)과 충돌하지 않도록
아래 기준을 사용합니다.

| 항목 | 값 |
| --- | --- |
| Host | `localhost` |
| Port | `5433` |
| DB명 | `dont_paw_get_record` |

### DATABASE_URL 설정

`DATABASE_URL`은 기본값이 없는 필수 환경변수입니다. `.env.example`을 참고해
`.env` 파일에 아래와 같은 형식으로 값을 채워주세요.

```
DATABASE_URL=postgresql+psycopg://record_user:record_password@localhost:5433/dont_paw_get_record
```

`.env` 파일은 Git에 포함되지 않으며, 실제 비밀번호나 운영 DB 정보를
`.env.example`이나 코드에 작성하지 않습니다.

### 로컬 PostgreSQL 준비 (Docker 기준, 예시)

아래는 참고용 예시입니다. 실제 컨테이너 생성/실행은 각자 로컬 환경에서
직접 수행해주세요.

```powershell
docker run --name dont-paw-get-record-db `
  -e POSTGRES_USER=record_user `
  -e POSTGRES_PASSWORD=record_password `
  -e POSTGRES_DB=dont_paw_get_record `
  -p 5433:5432 `
  -d postgres:16
```

### Alembic 기본 사용법

```powershell
# 현재 적용된 migration revision 확인
alembic current

# 최신 revision까지 migration 적용
alembic upgrade head

# migration 스크립트와 실제 DB 상태 불일치 여부 확인
alembic check
```

향후 실제 모델(BOOK, SCRAP 등)이 추가되면 아래 명령으로 migration을
생성합니다. (참고용, 이번 Jira에서는 사용하지 않음)

```powershell
alembic revision --autogenerate -m "<message>"
```

**CLIAR-39에서는 실제 업무 테이블 및 migration revision을 생성하지 않습니다.**
이번 단계는 SQLAlchemy/Alembic이 PostgreSQL과 연결될 수 있는 기반 구조만
준비하는 것을 목표로 합니다.

## OCR 문장/책 표지 텍스트 추출 API (AWS Bedrock Qwen3-VL)

Frontend에서 Crop/회전까지 완료된 최종 책 문장/표지 이미지를 업로드하면,
AWS Bedrock Qwen3-VL을 통해 텍스트를 추출한 뒤 아래와 같은 형태로
반환합니다. (CLIAR-143: OCR Provider를 NAVER CLOVA OCR에서 AWS Bedrock
Qwen3-VL로 완전히 전환했습니다. CLOVA credential은 더 이상 필요하지
않습니다.)

```
POST /api/v1/ocr/sentences
Content-Type: multipart/form-data

필드: image (image/jpeg 또는 image/png, 최대 50MB)
쿼리 파라미터(선택):
  - model_id: 사용할 Bedrock 모델 ID (기본값: "qwen.qwen3-vl-235b-a22b")
```

응답 예시:

```json
{
  "text": "첫 번째 줄\n두 번째 줄",
  "lines": ["첫 번째 줄", "두 번째 줄"],
  "request_id": "…",
  "confidence": 0.97,
  "provider": "bedrock"
}
```

책 표지에서 제목/저자 후보를 추출하는 API도 동일하게 Bedrock을 사용합니다.

```
POST /api/v1/ocr/covers
Content-Type: multipart/form-data

필드: image (image/jpeg 또는 image/png, 최대 50MB)
```

응답 예시:

```json
{
  "title_candidate": "성공하는 인생의 비밀",
  "author_candidates": ["이수진 지음"],
  "lines": ["성공하는 인생의 비밀", "성공하는 사람들의 비밀을 풀어라!", "이수진 지음"],
  "request_id": "…",
  "confidence": null
}
```

AWS Bedrock Qwen3-VL은 CLOVA `inferConfidence`와 동일한 의미의 공식 OCR
confidence를 제공하지 않으므로, `/covers` 응답의 `confidence`는 항상
`null`로 반환됩니다.

### 환경변수 설정

`.env` 파일에 필요한 AWS Bedrock 설정을 구성할 수 있습니다:

```env
# AWS Bedrock OCR 설정
AWS_REGION=us-east-1
AWS_PROFILE=kosa-mfa
BEDROCK_OCR_MODEL_ID=qwen.qwen3-vl-235b-a22b
```

### Bedrock Qwen3-VL OCR 테스트 방법

#### 1. CLI 스크립트로 직접 테스트하기
별도의 서버 실행 없이 바로 Bedrock Qwen3-VL 모델을 호출해볼 수 있는 테스트 스크립트가 제공됩니다.

```bash
# 자동 생성된 샘플 책 표지 이미지로 테스트
AWS_PROFILE=kosa-mfa uv run python scripts/test_bedrock_ocr.py

# 사용자가 가진 실제 책 이미지로 테스트
AWS_PROFILE=kosa-mfa uv run python scripts/test_bedrock_ocr.py path/to/book_cover.jpg
```

#### 2. API 서버를 통한 테스트
```bash
# 서버 실행
uv run uvicorn app.main:app --reload

# curl로 Bedrock OCR 호출
curl -X POST "http://127.0.0.1:8000/api/v1/ocr/sentences" \
  -F "image=@path/to/image.jpg;type=image/jpeg"
```

일반 `pytest` 실행 시에는 실제 외부 API를 호출하지 않으며 모든 네트워크 호출이 mock으로 대체되어 안전하게 실행됩니다.
