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
