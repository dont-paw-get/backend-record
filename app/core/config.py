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


settings = Settings()
