"""Noti(모니터링 알림 에이전트) API 요청/응답 스키마."""
from typing import Any

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    """POST /api/v1/noti/alert 요청 스키마(범용 알림 인입).

    GitHub Actions 외의 임의 모니터링 소스(인프라 헬스 체크, 외부 감시 도구,
    애플리케이션 에러 등)가 이벤트를 밀어 넣을 때 사용하는 일반 포맷이다.
    """

    source: str = Field(description="이벤트 발생 소스(예: 'infra-health', 'uptime-robot')")
    status: str = Field(description="상태 문자열(예: 'down', 'up', 'degraded', 'error')")
    message: str = Field(description="사람이 읽을 수 있는 이벤트 설명")
    severity: str | None = Field(
        default=None,
        description="힌트용 심각도. 없으면 에이전트가 스스로 판단한다.",
    )
    health_check_url: str | None = Field(
        default=None,
        description="에이전트가 현재 상태를 실제로 확인할 수 있는 URL(예: /health).",
    )
    details: dict[str, Any] | None = Field(
        default=None, description="부가 상세 정보(자유 형식)."
    )


class NotiResponse(BaseModel):
    """Noti webhook 처리 결과 응답 스키마."""

    status: str = Field(description="처리 상태(accepted | ignored | pong)")
    detail: str | None = Field(default=None, description="부가 설명")
