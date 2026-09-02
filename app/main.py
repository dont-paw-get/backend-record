from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.ocr import router as ocr_router
from app.core.logging_config import configure_logging
from app.core.observability import configure_tracing

# 로깅은 라우터 등록/트레이싱 구성보다 먼저 설정해 초기화 로그도 JSON 으로 남긴다.
configure_logging()

app = FastAPI(title="backend-record")

# OpenTelemetry 트레이싱 연결(CLIAR-201).
# OTEL_EXPORTER_OTLP_ENDPOINT 미설정 시 no-op 이며 앱은 정상 기동한다.
configure_tracing(app)

app.include_router(health_router)
app.include_router(ocr_router)
