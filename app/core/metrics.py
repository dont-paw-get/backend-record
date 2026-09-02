"""Prometheus HTTP 메트릭 노출 (관측 인프라 연동 - 작업 1).

dont-paw-get/infra 의 Prometheus 가 ServiceMonitor 로 이 서비스의
``/metrics`` 를 스크레이핑하고, "HTTP 5xx 에러율" / "p99 레이턴시" 알림
규칙과 RCA Agent 가 이 메트릭을 사용한다.

설계 원칙
---------
* backend-record 는 Spring 이 아니므로 Micrometer actuator 가 없다. 대신
  Spring Boot 의 ``http_server_requests_seconds`` 히스토그램과 **동일한
  메트릭 이름 / 라벨(application, method, uri, status, outcome)** 로 노출해
  infra 의 알림 규칙 쿼리가 Spring 서비스와 동일하게 동작하도록 한다.
    - ``http_server_requests_seconds_count``  : 요청 수(status 라벨 포함) → 5xx 에러율
    - ``http_server_requests_seconds_bucket`` : 요청 지연 히스토그램(le 라벨) → p99 레이턴시
    - ``http_server_requests_seconds_sum``
* 메트릭 태그 ``application`` 값은 ``OTEL_SERVICE_NAME`` 과 반드시 같다.
  RCA Agent 가 메트릭 ↔ 로그(``service``) ↔ 트레이스(``service.name``) 를
  같은 서비스로 상관분석하기 때문이다.
* ``/health`` 와 ``/metrics`` 자체는 probe·스크레이핑 경로이므로 집계에서 제외한다.
* 계측/노출 초기화 실패가 앱 기동이나 요청 처리를 막지 않도록 try/except 로 감싼다.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_configured = False

# Micrometer 기본값에 맞춘 지연 히스토그램 버킷(초 단위). p99 알림이 쓰는
# ``le`` 경계이므로 촘촘한 하위 구간을 유지한다.
_LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75,
    1.0, 2.5, 5.0, 7.5, 10.0,
)


def _outcome(status_code: int) -> str:
    """HTTP status code 를 Micrometer ``outcome`` 라벨 값으로 변환한다."""
    if 100 <= status_code < 200:
        return "INFORMATIONAL"
    if 200 <= status_code < 300:
        return "SUCCESS"
    if 300 <= status_code < 400:
        return "REDIRECTION"
    if 400 <= status_code < 500:
        return "CLIENT_ERROR"
    if 500 <= status_code < 600:
        return "SERVER_ERROR"
    return "UNKNOWN"


def configure_metrics(app) -> None:
    """FastAPI ``app`` 에 Prometheus 메트릭 계측과 ``/metrics`` 엔드포인트를 붙인다(멱등)."""
    global _configured
    if _configured:
        return
    _configured = True

    if not settings.METRICS_ENABLED:
        logger.info("METRICS_ENABLED is false; Prometheus metrics disabled.")
        return

    try:
        _configure(app)
        logger.info(
            "Prometheus metrics enabled",
            extra={"metrics_endpoint": "/metrics", "metrics_application": settings.OTEL_SERVICE_NAME},
        )
    except Exception:  # noqa: BLE001 - 메트릭 초기화 실패가 앱 기동을 막으면 안 된다.
        logger.exception("Failed to initialize Prometheus metrics; continuing without them.")


def _configure(app) -> None:
    from prometheus_client import Histogram
    from prometheus_fastapi_instrumentator import Instrumentator
    from prometheus_fastapi_instrumentator.metrics import Info

    application = settings.OTEL_SERVICE_NAME

    # Spring Boot(Micrometer) 호환 메트릭. 하나의 히스토그램이 _count(요청 수)/
    # _bucket(지연 분포)/_sum 을 모두 노출하므로 infra 의 5xx 에러율·p99 쿼리가
    # 그대로 동작한다.
    request_seconds = Histogram(
        "http_server_requests_seconds",
        "HTTP server request latency and count (Micrometer-compatible).",
        labelnames=("application", "method", "uri", "status", "outcome"),
        buckets=_LATENCY_BUCKETS,
    )

    def _instrumentation(info: Info) -> None:
        try:
            code = int(info.modified_status)
        except (TypeError, ValueError):
            code = 0
        request_seconds.labels(
            application=application,
            method=info.method,
            uri=info.modified_handler,
            status=info.modified_status,
            outcome=_outcome(code),
        ).observe(info.modified_duration)

    instrumentator = Instrumentator(
        should_group_status_codes=False,  # 5xx 알림이 개별 status code 를 필요로 한다.
        should_ignore_untemplated=True,   # 매칭되지 않는 경로(404 스캔 등)는 uri 카디널리티 폭증 방지로 무시.
        excluded_handlers=["/health", "/metrics"],
    )
    instrumentator.add(_instrumentation)
    instrumentator.instrument(app)
    # /metrics 는 별도 포트 없이 기존 http 포트(8000)에 노출한다.
    instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
