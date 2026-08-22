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

    # PostgreSQL 연결 문자열. 기본값을 두지 않고 필수 환경변수로 요구합니다.
    # 실제 값은 .env 파일(로컬) 또는 배포 환경의 환경변수로 주입합니다.
    DATABASE_URL: str

    # NAVER Cloud CLOVA OCR General API 연결 정보. 기본값을 두지 않고
    # 필수 환경변수로 요구합니다. 실제 URL/Secret 값은 코드에 작성하지
    # 않으며, .env 파일(로컬) 또는 배포 환경의 환경변수로 주입합니다.
    CLOVA_OCR_INVOKE_URL: str
    CLOVA_OCR_SECRET_KEY: str

    # --- Noti: 인프라/CI-CD 모니터링 알림 에이전트 ---
    DISCORD_WEBHOOK_URL: str | None = None
    GITHUB_WEBHOOK_SECRET: str | None = None

    # Strands Agents가 사용할 LLM 프로바이더. "anthropic" | "bedrock".
    # 기본은 anthropic(= ANTHROPIC_API_KEY만 있으면 동작). 추후 AWS/Bedrock이
    # 준비되면 "bedrock"으로 바꾸고 NOTI_AWS_REGION만 지정하면 된다.
    NOTI_MODEL_PROVIDER: str = "anthropic"

    # 사용할 모델 ID. 지정하지 않으면 프로바이더별 기본값을 사용한다.
    NOTI_MODEL_ID: str | None = None

    # 에이전트 1회 응답의 최대 토큰 수(알림 요약은 짧으므로 넉넉히 1024).
    NOTI_MAX_TOKENS: int = 1024

    # Anthropic API 직접 연동(NOTI_MODEL_PROVIDER="anthropic") 시 필요한 키.
    ANTHROPIC_API_KEY: str | None = None

    # Bedrock 연동(NOTI_MODEL_PROVIDER="bedrock") 시 사용할 AWS 리전.
    NOTI_AWS_REGION: str | None = None


settings = Settings()
