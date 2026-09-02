"""OpenTelemetry 분산 트레이싱 초기화 (CLIAR-201).

애플리케이션이 ``opentelemetry-instrument`` 같은 실행 wrapper 없이,
기존 ``uvicorn app.main:app`` 실행 구조를 그대로 유지한 채 코드 내부에서
명시적으로 트레이싱을 구성한다.

설계 원칙
---------
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` 가 설정된 경우에만 exporter/instrumentation
  을 활성화한다. 값이 없으면(로컬 개발) 아무것도 하지 않고 그대로 반환하며,
  애플리케이션은 정상 기동한다(트레이싱은 no-op).
* Collector 로의 전송은 ``BatchSpanProcessor`` 가 **백그라운드 스레드**에서
  수행하고 exporter 오류를 내부적으로 삼키므로, Collector 장애가 record API
  요청 처리 실패로 이어지지 않는다. 초기화 자체도 try/except 로 감싸 startup
  을 막지 않는다.
* Resource 에 ``service.name`` 과 실행 환경 정보(``deployment.environment``,
  ``service.instance.id`` 등)를 담는다.
* W3C Trace Context 전파를 사용한다(botocore instrumentation 이 끌어오는
  AWS X-Ray 전파기를 쓰지 않도록 전역 propagator 를 명시적으로 고정한다).
* ``/health``(K8s probe), ``/metrics``(Prometheus 스크레이핑) 는 server span
  대상에서 제외한다.
"""
from __future__ import annotations

import logging
import os
import socket

from app.core.config import settings

logger = logging.getLogger(__name__)

_configured = False


def configure_tracing(app) -> None:
    """FastAPI ``app`` 에 OpenTelemetry 트레이싱을 연결한다(멱등).

    Args:
        app: ``fastapi.FastAPI`` 인스턴스.
    """
    global _configured
    if _configured:
        return

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if not endpoint:
        logger.info(
            "OTEL_EXPORTER_OTLP_ENDPOINT is not set; tracing disabled (no-op)."
        )
        _configured = True
        return

    try:
        _configure(app, endpoint.rstrip("/"))
        _configured = True
        logger.info(
            "OpenTelemetry tracing enabled",
            extra={
                "otel_endpoint": f"{endpoint.rstrip('/')}/v1/traces",
                "otel_service_name": settings.OTEL_SERVICE_NAME,
                "otel_traces_sampler_arg": settings.OTEL_TRACES_SAMPLER_ARG,
            },
        )
    except Exception:  # noqa: BLE001 - 트레이싱 초기화 실패가 앱 기동을 막으면 안 된다.
        logger.exception("Failed to initialize OpenTelemetry tracing; continuing without it.")


def _configure(app, endpoint: str) -> None:
    from opentelemetry import trace
    from opentelemetry.baggage.propagation import W3CBaggagePropagator
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    pod_name = os.getenv("POD_NAME")
    resource_attributes = {
        "service.name": settings.OTEL_SERVICE_NAME,
        "deployment.environment": settings.APP_ENV,
        "service.instance.id": pod_name or socket.gethostname(),
    }
    if settings.OTEL_SERVICE_VERSION:
        resource_attributes["service.version"] = settings.OTEL_SERVICE_VERSION
    if pod_name:
        resource_attributes["k8s.pod.name"] = pod_name
    if os.getenv("POD_NAMESPACE"):
        resource_attributes["k8s.namespace.name"] = os.environ["POD_NAMESPACE"]
    if os.getenv("NODE_NAME"):
        resource_attributes["k8s.node.name"] = os.environ["NODE_NAME"]

    # Resource.create() 는 OTEL_RESOURCE_ATTRIBUTES 등 표준 환경변수와
    # telemetry.sdk.* 정보를 함께 병합한다.
    resource = Resource.create(resource_attributes)

    sampler = ParentBased(TraceIdRatioBased(float(settings.OTEL_TRACES_SAMPLER_ARG)))

    provider = TracerProvider(resource=resource, sampler=sampler)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )

    # 이미 실제 provider 가 설정돼 있으면(테스트 등) 덮어쓰지 않는다.
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        logger.info("TracerProvider already set; reusing existing provider.")
        provider = current
    else:
        trace.set_tracer_provider(provider)

    # W3C Trace Context + Baggage 전파를 명시적으로 고정한다.
    set_global_textmap(
        CompositePropagator(
            [TraceContextTextMapPropagator(), W3CBaggagePropagator()]
        )
    )

    _instrument(app, provider)


def _instrument(app, provider) -> None:
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    # inbound HTTP(server span). /health(probe), /metrics(Prometheus 스크레이핑)
    # 는 트레이스를 만들지 않는다 (ADR-0007 #4).
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls="health,metrics"
    )
    # outbound: backend-auth / backend-book 호출(app/providers/*.py 의 httpx.AsyncClient)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    # outbound: AWS Bedrock Runtime converse 호출(app/services/bedrock_ocr.py)
    BotocoreInstrumentor().instrument(tracer_provider=provider)
