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

    # CLIAR-143: OCR Provider를 AWS Bedrock Qwen3-VL로 완전히 전환하여
    # NAVER CLOVA OCR 관련 설정(CLOVA_OCR_INVOKE_URL, CLOVA_OCR_SECRET_KEY,
    # OCR_PROVIDER)을 제거했습니다. backend-record는 이제 AWS Bedrock만
    # 사용하며 CLOVA credential이 필요하지 않습니다.

    # AWS Bedrock OCR 설정
    # AWS_REGION 은 파드/서비스의 홈 리전(서울, ap-northeast-2)이며 STS 등 일반
    # AWS 호출에 쓰인다. EKS IRSA 웹훅이 이 값을 클러스터 리전으로 주입한다.
    AWS_REGION: str = "us-east-1"
    # BEDROCK_REGION 은 Bedrock 호출에만 사용하는 전용 리전. Qwen3-VL 모델이
    # us-east-1 에만 있으므로 여기서 분리해 지정한다. (미지정 시 us-east-1)
    BEDROCK_REGION: str = "us-east-1"
    AWS_PROFILE: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_SESSION_TOKEN: str | None = None
    BEDROCK_OCR_MODEL_ID: str = "qwen.qwen3-vl-235b-a22b"

    # RECORD-1: 스크랩 이미지를 저장하는 S3 버킷. 비밀값이 아니므로 ConfigMap/
    # 환경변수로 주입하며(app/services/s3_upload.py), 코드에 하드코딩하지 않는다.
    SCRAP_S3_BUCKET: str = "dpyb-scrap-image"

    # RECORD-2: 업로드된 스크랩 이미지를 서비스하는 CloudFront 도메인(scheme 없음).
    # URL 조합은 app/services/s3_upload.py의 build_cloudfront_url() 한 곳에서만 한다.
    SCRAP_CLOUDFRONT_DOMAIN: str = "d3qnwig98jio0e.cloudfront.net"

    AUTH_API: str

    # backend-book 서재 API Base URL. /covers OCR 이후 사용자의 개인 서재에
    # 책을 등록(POST /api/v1/library/books)하기 위해 사용한다.
    BOOK_API: str


settings = Settings()
