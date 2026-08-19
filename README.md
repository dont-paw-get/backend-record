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
