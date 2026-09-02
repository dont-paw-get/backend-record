"""CLIAR-201: 구조화 JSON 로깅 / OpenTelemetry 트레이싱 초기화 단위 테스트.

실제 OTel Collector 없이 검증 가능한 범위만 다룬다.
"""
import asyncio
import json
import logging
from unittest.mock import MagicMock

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.logging_config import JsonFormatter, configure_logging
from app.core.observability import configure_tracing
from app.services import bedrock_ocr


def _make_record(msg: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_outputs_single_line_valid_json():
    out = JsonFormatter("backend-record").format(_make_record("ocr processing completed"))

    assert "\n" not in out
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["service"] == "backend-record"
    assert parsed["logger"] == "app.test"
    assert parsed["message"] == "ocr processing completed"
    assert "timestamp" in parsed
    # 활성 span 이 없으면 trace_id/span_id 는 생략된다.
    assert "trace_id" not in parsed
    assert "span_id" not in parsed


def test_json_formatter_injects_trace_and_span_id_within_active_span():
    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("unit-span"):
        parsed = json.loads(JsonFormatter("backend-record").format(_make_record()))

    assert len(parsed["trace_id"]) == 32
    int(parsed["trace_id"], 16)  # hex 문자열이어야 한다
    assert len(parsed["span_id"]) == 16
    int(parsed["span_id"], 16)


def test_json_formatter_redacts_sensitive_extra_fields():
    parsed = json.loads(
        JsonFormatter("backend-record").format(
            _make_record(authorization="Bearer secret", ocr_line_count=3)
        )
    )

    assert parsed["authorization"] == "[REDACTED]"
    assert parsed["ocr_line_count"] == 3


def test_json_formatter_includes_exception_field():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="app.test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    parsed = json.loads(JsonFormatter("backend-record").format(record))

    assert "ValueError: boom" in parsed["exception"]


def test_configure_tracing_is_noop_without_endpoint(monkeypatch):
    """OTEL_EXPORTER_OTLP_ENDPOINT 미설정 시 예외 없이 no-op 이어야 한다."""
    import app.core.observability as obs
    from app.core.config import settings

    monkeypatch.setattr(obs, "_configured", False)
    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None)

    configure_tracing(object())  # 예외가 발생하지 않아야 한다.


def test_record_ocr_custom_span_carries_only_safe_metadata(monkeypatch):
    """OCR 서비스가 'record.ocr' 상위 span 을 만들고, 원문/이미지 바이트가
    아닌 메타데이터(타입/포맷/길이/모델/줄 수)만 span 에 담는지 확인한다."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(bedrock_ocr, "_tracer", provider.get_tracer("test"))

    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": "first\nsecond"}]}},
        "ResponseMetadata": {"RequestId": "req-1"},
    }

    asyncio.run(
        bedrock_ocr.extract_text_from_image(b"secret-image-bytes", "jpg", client=fake_client)
    )

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "record.ocr" in spans
    attrs = spans["record.ocr"].attributes
    assert attrs["record.ocr.type"] == "sentences"
    assert attrs["record.ocr.image_format"] == "jpeg"
    assert attrs["record.ocr.line_count"] == 2
    # 원문 텍스트/이미지 바이트가 attribute 로 새어나가지 않아야 한다.
    serialized = json.dumps(dict(attrs), default=str)
    assert "secret-image-bytes" not in serialized
    assert "first" not in serialized


def test_configure_logging_installs_exactly_one_json_handler_on_stdout():
    import sys

    configure_logging()
    root = logging.getLogger()

    # pytest 가 자체 capture handler 를 root 에 추가하므로 전체 개수는 세지 않고,
    # JsonFormatter 를 쓰는 stdout 핸들러가 정확히 1개인지만 확인한다.
    json_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and isinstance(h.formatter, JsonFormatter)
    ]
    assert len(json_handlers) == 1
    assert json_handlers[0].stream is sys.stdout
