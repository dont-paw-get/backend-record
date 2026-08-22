"""Noti - 인프라/CI-CD 모니터링 알림 에이전트 (Strands Agents).

CI/CD·인프라 이벤트(webhook)를 입력받아, LLM 에이전트가 심각도와 핵심 내용을
판단하고 사람이 읽기 좋은 한국어 Discord 알림을 작성/전송한다.
"""
import json
import logging

import httpx

from app.core.config import settings
from app.services import discord

logger = logging.getLogger(__name__)

# 헬스 체크 툴의 HTTP timeout (초).
HEALTH_CHECK_TIMEOUT_SECONDS = 10.0

# anthropic 프로바이더에서 NOTI_MODEL_ID 미지정 시 사용할 기본 모델.
DEFAULT_ANTHROPIC_MODEL_ID = "claude-opus-4-8"


SYSTEM_PROMPT = """당신은 "Noti"라는 이름의 인프라/CI-CD 모니터링 알림 에이전트입니다.
GitHub Actions(CI/CD) 결과와 인프라 헬스 이벤트를 전달받아, 운영팀이 Discord에서
빠르게 상황을 파악할 수 있도록 정확하고 간결한 한국어 알림을 작성합니다.

행동 규칙:
1. 전달받은 이벤트를 분석해 심각도(severity)를 판단합니다.
   - success: 성공/복구 등 긍정적 결과
   - info: 참고성 정보
   - warning: 주의가 필요하나 즉시 장애는 아닌 상태
   - critical: 배포 실패, 서비스 다운 등 즉시 대응이 필요한 상태
2. 인프라 헬스 관련 이벤트에서 현재 상태가 불확실하면, check_service_health
   툴로 대상 URL을 실제로 확인한 뒤 심각도를 확정합니다.
3. 판단이 끝나면 반드시 send_discord_notification 툴을 정확히 한 번 호출해
   알림을 전송합니다. 제목은 한눈에 상황을 알 수 있게, 본문은 핵심 원인과
   필요한 조치를 3줄 이내로 요약합니다. 로그 원문을 그대로 붙여넣지 마세요.
4. 관련 링크(예: 워크플로 실행 URL)가 있으면 link 인자로 전달합니다.
5. 툴 호출을 마친 뒤에는 무엇을 왜 그렇게 알렸는지 한 문장으로만 요약합니다."""


async def _tool_send_discord_notification(
    title: str,
    summary: str,
    severity: str = "info",
    fields: dict[str, str] | None = None,
    link: str = "",
) -> str:
    """작성한 알림을 Discord 채널로 전송한다.

    Args:
        title: 알림 제목. 상황을 한눈에 알 수 있게 작성한다.
        summary: 알림 본문. 핵심 원인과 필요한 조치를 간결히 요약한다(마크다운 가능).
        severity: 심각도. "success" | "info" | "warning" | "critical" 중 하나.
        fields: Discord embed에 표시할 부가 정보({이름: 값}). 예: {"저장소": "org/repo", "브랜치": "main"}.
        link: 제목에 연결할 링크(예: GitHub Actions 실행 URL). 없으면 빈 문자열.
    """
    await discord.send_discord_notification(
        title=title,
        description=summary,
        severity=severity,
        fields=fields,
        url=link or None,
    )
    return f"Discord 알림 전송 완료 (severity={severity})"


async def _tool_check_service_health(url: str) -> str:
    """주어진 URL(예: /health 엔드포인트)에 GET 요청을 보내 현재 서비스 상태를 확인한다.

    Args:
        url: 상태를 확인할 대상 URL.
    """
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return f"요청 실패: {type(exc).__name__} ({url})"
    return f"HTTP {response.status_code} ({url}): {response.text[:500]}"


class NotiAgentError(Exception):
    """Noti 에이전트 실행 관련 오류(모델 설정 누락, 실행 실패 등)."""


def _build_model():
    """settings.NOTI_MODEL_PROVIDER에 따라 Strands 모델 인스턴스를 생성한다."""
    provider = settings.NOTI_MODEL_PROVIDER.lower()

    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise NotiAgentError("ANTHROPIC_API_KEY is not configured")
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": settings.ANTHROPIC_API_KEY},
            model_id=settings.NOTI_MODEL_ID or DEFAULT_ANTHROPIC_MODEL_ID,
            max_tokens=settings.NOTI_MAX_TOKENS,
        )

    if provider == "bedrock":
        from strands.models import BedrockModel

        kwargs: dict = {"max_tokens": settings.NOTI_MAX_TOKENS}
        if settings.NOTI_MODEL_ID:
            kwargs["model_id"] = settings.NOTI_MODEL_ID
        if settings.NOTI_AWS_REGION:
            kwargs["region_name"] = settings.NOTI_AWS_REGION
        return BedrockModel(**kwargs)

    raise NotiAgentError(f"Unsupported NOTI_MODEL_PROVIDER: {settings.NOTI_MODEL_PROVIDER}")


# 에이전트는 모델 클라이언트 초기화 비용이 있으므로 최초 사용 시 1회만 생성한다.
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from strands import Agent, tool

        _agent = Agent(
            model=_build_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=[
                tool(_tool_send_discord_notification),
                tool(_tool_check_service_health),
            ],
        )
    return _agent


def _build_prompt(event_kind: str, payload: dict) -> str:
    """webhook 이벤트를 에이전트 입력 프롬프트로 변환한다."""
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return (
        f"다음은 '{event_kind}' 유형의 모니터링 이벤트입니다. 내용을 분석해 "
        f"심각도를 판단하고 Discord 알림을 전송하세요.\n\n"
        f"```json\n{payload_json}\n```"
    )


async def run_noti_agent(event_kind: str, payload: dict) -> str:
    """모니터링 이벤트를 에이전트에 전달해 분석·알림 전송을 수행한다.

    Args:
        event_kind: 이벤트 종류 식별자(예: "github_workflow_run", "alert").
        payload: 이벤트 상세 데이터.

    Returns:
        에이전트가 남긴 최종 요약 텍스트.

    Raises:
        NotiAgentError: 모델 설정 누락 또는 에이전트 실행 실패 시.
    """
    prompt = _build_prompt(event_kind, payload)
    logger.info("Running Noti agent (event_kind=%s)", event_kind)

    try:
        agent = _get_agent()
        result = await agent.invoke_async(prompt)
    except NotiAgentError:
        raise
    except Exception as exc:  # 모델/툴/네트워크 등 예기치 못한 실패를 일원화
        logger.exception("Noti agent run failed (event_kind=%s)", event_kind)
        raise NotiAgentError("Noti agent run failed") from exc

    logger.info("Noti agent finished (event_kind=%s)", event_kind)
    return str(result)