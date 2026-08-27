"""pytest 전역 설정.

app.core.config.Settings는 DATABASE_URL, CLOVA_OCR_INVOKE_URL,
CLOVA_OCR_SECRET_KEY를 기본값 없는 필수 값으로 요구한다. 테스트이 실행자의
로컬 .env 파일 존재 여부에 의존하지 않도록, 테스트 모듈이 import되기 전에
(conftest.py는 pytest가 테스트를 수집하기 전에 가장 먼저 로드된다) 안전한
dummy 값을 환경변수에 채워 넣는다.

pydantic-settings는 실제 OS 환경변수를 .env 파일보다 우선하므로, 여기서
설정한 값이 로컬 .env의 실제 값보다 먼저 적용되어 테스트가 항상 동일하게
동작한다. 이미 환경변수가 설정되어 있는 경우(예: CI에서 별도로 주입한
값)는 setdefault로 덮어쓰지 않는다.

주의: 아래 값은 테스트 전용 dummy 값이며 실제 CLOVA OCR Secret이 아니다.
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
