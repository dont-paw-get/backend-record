from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 기본 환경변수 설정.

    이번 Jira(CLIAR-38) 범위에서는 애플리케이션 실행에 필요한
    최소한의 값만 정의합니다. DB/AWS 관련 설정은 해당 기능 Jira에서 추가합니다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "local"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # PostgreSQL 연결 문자열.
    #
    # CLIAR-123: backend-record는 Scrap 저장 책임(CLIAR-121)과 함께
    # DB/Alembic 배포 의존성도 더 이상 필요로 하지 않는 CLOVA OCR 전용
    # 서비스입니다. 따라서 DATABASE_URL을 필수 값에서 optional(기본값
    # None)로 변경했습니다. DB 환경변수가 전혀 없는 배포 환경에서도
    # app.main import/startup이 실패하지 않아야 합니다.
    # app/core/database.py, alembic/은 과거 마이그레이션 history 보존
    # 목적으로 코드 자체는 유지하되, 이 값이 없으면 사용하지 않습니다.
    DATABASE_URL: str | None = None

    # NAVER Cloud CLOVA OCR General API 연결 정보. 기본값을 두지 않고
    # 필수 환경변수로 요구합니다. 실제 URL/Secret 값은 코드에 작성하지
    # 않으며, .env 파일(로컬) 또는 배포 환경의 환경변수로 주입합니다.
    CLOVA_OCR_INVOKE_URL: str
    CLOVA_OCR_SECRET_KEY: str


settings = Settings()
