"""CLIAR-123: backend-record가 DB/Alembic 배포 의존성 없이 기동 가능한지 검증.

backend-record는 최종적으로 CLOVA OCR 전용 서비스이며, Scrap 저장 책임은
CLIAR-121에서 이미 제거되었다. 이 테스트는 DATABASE_URL을 포함한 DB 관련
환경변수가 전혀 없어도 app.main이 import되고, health/OCR 라우트가
OpenAPI에 정상 노출되는지 확인한다.

app.main을 이 프로세스 안에서 재import(sys.modules 조작)하면, app.api.ocr
등 하위 모듈 객체가 교체되면서 다른 테스트 파일(예: test_ocr_api.py)이
가진 기존 module 참조와 어긋나는 테스트 오염이 발생한다. 이를 피하기
위해 별도의 subprocess에서 실행해 이 프로세스의 sys.modules 상태에
영향을 주지 않도록 검증한다.

실제 CLOVA OCR API는 호출하지 않는다.
"""
import json
import subprocess
import sys


def _run_in_subprocess(code: str, env_overrides: dict) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ}
    env.pop("DATABASE_URL", None)
    env.update(env_overrides)

    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


DUMMY_CLOVA_ENV = {
    "CLOVA_OCR_INVOKE_URL": "https://example.apigw.ntruss.com/custom/v1/00000/xxxxxxxx/general",
    "CLOVA_OCR_SECRET_KEY": "dummy-test-secret-key",
}


def test_app_main_imports_without_database_url():
    result = _run_in_subprocess(
        "import app.main; print('OK')", DUMMY_CLOVA_ENV
    )

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_openapi_schema_generated_without_database_url_lists_expected_routes():
    code = (
        "import json; import app.main; "
        "print(json.dumps(sorted(app.main.app.openapi()['paths'].keys())))"
    )
    result = _run_in_subprocess(code, DUMMY_CLOVA_ENV)

    assert result.returncode == 0, result.stderr
    paths = set(json.loads(result.stdout.strip().splitlines()[-1]))

    assert "/health" in paths
    assert "/api/v1/ocr/sentences" in paths
    assert "/api/v1/scraps" not in paths


def test_settings_does_not_require_database_url():
    """DATABASE_URL 없이 Settings를 직접 생성해도 예외 없이 None으로 채워지는지 확인한다.

    app.core.config는 app.services.clova_ocr 등 다른 모듈이 이미
    import해서 캐시하고 있으므로, 이 프로세스 안에서 재import(sys.modules
    조작)하면 다른 테스트(예: test_ocr_api.py)가 참조하는 모듈 객체와
    어긋나는 오염이 발생할 수 있다. 이를 피하기 위해 별도 subprocess에서
    검증한다. 로컬 .env의 실제 DATABASE_URL 값도 subprocess의 환경변수를
    직접 제어해 격리한다.
    """
    code = (
        "from app.core.config import Settings; "
        "s = Settings(_env_file=None); "
        "assert s.DATABASE_URL is None, s.DATABASE_URL; "
        "print('OK')"
    )
    result = _run_in_subprocess(code, DUMMY_CLOVA_ENV)

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
