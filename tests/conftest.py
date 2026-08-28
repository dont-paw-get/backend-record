"""pytest 전역 설정.

app.core.config.Settings.DATABASE_URL은 optional(기본값 None)이지만,
tests/test_database.py는 실제 DATABASE_URL 값이 주입된 상태를 기준으로
검증하므로 테스트 실행자의 로컬 .env 파일 존재 여부에 의존하지 않도록
안전한 dummy 값을 환경변수에 채워 넣는다 (conftest.py는 pytest가 테스트를
수집하기 전에 가장 먼저 로드된다).

pydantic-settings는 실제 OS 환경변수를 .env 파일보다 우선하므로, 여기서
설정한 값이 로컬 .env의 실제 값보다 먼저 적용되어 테스트가 항상 동일하게
동작한다. 이미 환경변수가 설정되어 있는 경우(예: CI에서 별도로 주입한
값)는 setdefault로 덮어쓰지 않는다.

CLIAR-143: OCR Provider가 AWS Bedrock으로 전환되어 CLOVA_OCR_* 환경변수는
더 이상 필요하지 않다.
"""
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test_user:test_password@localhost:5433/test_db",
)
os.environ.setdefault(
    "CLOVA_OCR_INVOKE_URL",
    "https://example.apigw.ntruss.com/custom/v1/00000/xxxxxxxx/general",
)
os.environ.setdefault("CLOVA_OCR_SECRET_KEY", "dummy-test-secret-key")
os.environ.setdefault("OCR_PROVIDER", "clova")
os.environ.setdefault("AUTH_API", "http://auth.test.local")
os.environ.setdefault("BOOK_API", "http://book.test.local")
