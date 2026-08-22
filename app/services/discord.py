"""Discord Incoming Webhook 전송.
Noti 에이전트(app.services.noti_agent)의 send_discord_notification 툴이 최종적으로
이 모듈을 호출하며, 심각도(severity)에 따라 embed 색상이 결정된다.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Discord webhook 호출 timeout (초).
DISCORD_REQUEST_TIMEOUT_SECONDS = 10.0

# 심각도 -> Discord embed 색상(십진수). Discord는 embed color를 정수로 받는다.
SEVERITY_COLORS: dict[str, int] = {
    "info": 0x3498DB,  # 파랑
    "success": 0x2ECC71,  # 초록
    "warning": 0xE67E22,  # 주황
    "critical": 0xE74C3C,  # 빨강
}
DEFAULT_SEVERITY_COLOR = SEVERITY_COLORS["info"]


class DiscordError(Exception):
    """Discord 전송 관련 오류의 베이스 클래스."""


class DiscordNotConfiguredError(DiscordError):
    """DISCORD_WEBHOOK_URL이 설정되지 않은 경우."""


class DiscordSendFailedError(DiscordError):
    """Discord webhook 호출이 실패했거나(HTTP 오류, 네트워크 오류, timeout)
    2xx가 아닌 응답을 받은 경우."""


def _build_embed(
    title: str,
    description: str,
    severity: str,
    fields: dict[str, str] | None = None,
    url: str | None = None,
) -> dict:
    """Discord embed payload를 구성한다.

    fields는 {이름: 값} 형태의 부가 정보(예: repository, branch)이며 embed의
    inline field로 렌더링된다.
    """
    color = SEVERITY_COLORS.get(severity.lower(), DEFAULT_SEVERITY_COLOR)

    embed: dict = {
        "title": title[:256],  # Discord embed title 최대 길이
        "description": description[:4096],  # Discord embed description 최대 길이
        "color": color,
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = [
            {"name": str(name)[:256], "value": str(value)[:1024], "inline": True}
            for name, value in fields.items()
        ]
    return embed


async def send_discord_notification(
    title: str,
    description: str,
    severity: str = "info",
    fields: dict[str, str] | None = None,
    url: str | None = None,
) -> None:
    """Discord 채널로 알림 embed를 전송한다.

    Args:
        title: 알림 제목.
        description: 알림 본문(마크다운 지원).
        severity: 심각도. "info" | "success" | "warning" | "critical".
        fields: embed에 표시할 부가 정보({이름: 값}).
        url: 제목에 연결할 링크(예: GitHub Actions 실행 URL).

    Raises:
        DiscordNotConfiguredError: DISCORD_WEBHOOK_URL이 없는 경우.
        DiscordSendFailedError: 전송이 실패한 경우.
    """
    if not settings.DISCORD_WEBHOOK_URL:
        raise DiscordNotConfiguredError("DISCORD_WEBHOOK_URL is not configured")

    embed = _build_embed(title, description, severity, fields=fields, url=url)
    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient(timeout=DISCORD_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.DISCORD_WEBHOOK_URL, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning("Discord webhook request timed out")
        raise DiscordSendFailedError("Discord webhook request timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("Discord webhook request failed with %s", type(exc).__name__)
        raise DiscordSendFailedError("Discord webhook request failed") from exc

    # Discord webhook 성공 응답은 보통 204 No Content.
    if response.status_code not in (200, 204):
        logger.warning(
            "Discord webhook returned unexpected status: %s", response.status_code
        )
        raise DiscordSendFailedError(
            f"Discord webhook returned unexpected status: {response.status_code}"
        )

    logger.info("Discord notification sent (severity=%s)", severity)
