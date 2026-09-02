"""관측 인프라 연동 - 작업 1: Prometheus HTTP 메트릭 노출 단위 테스트."""
from fastapi.testclient import TestClient

from app.core.metrics import _outcome
from app.main import app

client = TestClient(app)


def test_outcome_maps_status_class_to_micrometer_label():
    assert _outcome(200) == "SUCCESS"
    assert _outcome(302) == "REDIRECTION"
    assert _outcome(404) == "CLIENT_ERROR"
    assert _outcome(500) == "SERVER_ERROR"
    assert _outcome(0) == "UNKNOWN"


def test_metrics_endpoint_exposes_micrometer_compatible_http_metrics():
    # 집계 대상 요청을 한 건 만든다(인증 없이 401 이지만 라우트는 템플릿 매칭됨).
    client.post("/api/v1/ocr/sentences")

    body = client.get("/metrics").text

    # infra 알림 규칙이 쓰는 메트릭 이름/라벨이 존재해야 한다.
    assert "http_server_requests_seconds_count{" in body
    assert "http_server_requests_seconds_bucket{" in body
    assert 'application="backend-record"' in body
    assert 'uri="/api/v1/ocr/sentences"' in body
    assert 'le="+Inf"' in body


def test_metrics_and_health_are_excluded_from_request_metrics():
    client.get("/health")
    client.get("/metrics")

    body = client.get("/metrics").text

    assert 'uri="/health"' not in body
    assert 'uri="/metrics"' not in body
