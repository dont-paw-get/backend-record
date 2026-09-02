"""stdout 구조화(JSON) 로깅 설정 (CLIAR-201).

운영 환경(Kubernetes)에서 컨테이너 stdout 을 Grafana Alloy 가 수집해
Loki 로 전송한다. 따라서 애플리케이션은 **파일이 아닌 stdout 으로**
한 줄당 하나의 valid JSON 로그를 출력하기만 하면 되고, 별도의 Loki
client 는 필요하지 않다.

로그 레코드에는 현재 활성 OpenTelemetry Span 의 ``trace_id`` /
``span_id`` 를 (W3C/Tempo 와 동일한 hex 표기로) 주입한다. 이를 통해
Grafana 에서 Loki 로그 ↔ Tempo Trace 를 동일 trace_id 로 상호 연결할 수
있다. ``trace_id`` / ``span_id`` 는 Loki label 이 아니라 JSON field 로만
유지한다.

활성 span 이 없으면(트레이싱 미구성 로컬 환경, 백그라운드 태스크 등)
``trace_id`` / ``span_id`` 는 출력하지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
from typing import Any

from opentelemetry import trace

from app.core.config import settings

# JSON 으로 그대로 노출하면 안 되는 LogRecord 표준 속성.
# 이 목록에 없는 커스텀 속성(logger.info(..., extra={...}))만 JSON 에 병합한다.
_RESERVED_LOGRECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}

# 민감정보가 자주 담기는 키. extra 로 실수로 넘어와도 로그에 남기지 않는다.
# (일차 방어선은 "애초에 넣지 않는 것"이며, 이건 보조 방어선이다.)
_SENSITIVE_EXTRA_KEYS = {
    "authorization", "cookie", "set-cookie", "access_token", "refresh_token",
    "id_token", "token", "password", "secret", "api_key", "apikey",
    "aws_secret_access_key", "aws_access_key_id", "aws_session_token",
}


def _trace_context() -> dict[str, str]:
    """현재 활성 span 에서 trace_id / span_id 를 hex 문자열로 추출한다.

    기록 중인(recording) 유효한 span 이 없으면 빈 dict 를 반환한다.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return {}
    return {
        "trace_id": trace.format_trace_id(ctx.trace_id),
        "span_id": trace.format_span_id(ctx.span_id),
    }


class JsonFormatter(logging.Formatter):
    """LogRecord 를 한 줄 JSON 으로 직렬화한다."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": self._service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        payload.update(_trace_context())

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            if key in payload:
                continue
            if key.lower() in _SENSITIVE_EXTRA_KEYS:
                payload[key] = "[REDACTED]"
                continue
            payload[key] = _coerce(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, ensure_ascii=False, default=str)


def _coerce(value: Any) -> Any:
    """json.dumps 가 처리할 수 있는 형태로 값을 변환한다."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, dict)):
        return value
    return str(value)


_configured = False


def configure_logging() -> None:
    """루트 로거에 stdout JSON 핸들러를 1개만 설정한다(멱등).

    uvicorn 이 관리하는 로거(uvicorn, uvicorn.error, uvicorn.access)도 자체
    핸들러를 비우고 루트로 전파시켜 동일한 JSON 포맷으로 출력되게 한다.
    """
    global _configured
    if _configured:
        return

    formatter = JsonFormatter(settings.OTEL_SERVICE_NAME)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _configured = True
