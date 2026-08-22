"""Noti - 인프라/CI-CD 모니터링 알림 webhook API (CLIAR-76).

두 개의 인입 경로를 제공한다.
- POST /api/v1/noti/github : GitHub Actions webhook(workflow_run) 수신.
- POST /api/v1/noti/alert  : 인프라 헬스 등 범용 알림 인입(JSON).

이 라우터는 서명 검증·이벤트 필터링·페이로드 정규화만 담당하고, 실제 분석과
Discord 전송은 Strands 에이전트(app.services.noti_agent)에 위임한다. 에이전트
실행은 LLM 호출을 포함해 시간이 걸릴 수 있으므로, webhook 응답을 빠르게 돌려주기
위해 BackgroundTasks로 비동기 처리한다.
"""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.config import settings
from app.schemas.noti import AlertPayload, NotiResponse
from app.services.discord import DiscordError
from app.services.noti_agent import NotiAgentError, run_noti_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/noti", tags=["noti"])

# GitHub Actions에서 실제로 알림을 만들 가치가 있는 이벤트만 통과시킨다.
# 진행 중(in_progress)·요청됨(requested) 등은 무시하고 완료된 실행만 처리한다.
_HANDLED_GITHUB_ACTION = "completed"


def _verify_github_signature(body: bytes, signature_header: str | None) -> None:
    """GitHub webhook의 HMAC-SHA256 서명을 검증한다.

    GITHUB_WEBHOOK_SECRET이 설정되지 않은 경우 검증을 건너뛴다(로컬 개발 편의).
    설정된 경우 서명이 없거나 일치하지 않으면 401을 발생시킨다.
    """
    if not settings.GITHUB_WEBHOOK_SECRET:
        return

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="서명 헤더(X-Hub-Signature-256)가 없습니다.",
        )

    expected = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="서명 검증에 실패했습니다.",
        )


def _summarize_workflow_run(payload: dict) -> dict:
    """GitHub workflow_run webhook 원본에서 알림에 필요한 필드만 추린다.

    원본 webhook은 매우 크므로, 에이전트 프롬프트에 넣기 좋은 최소한의
    정규화된 형태로 축약한다.
    """
    run = payload.get("workflow_run") or {}
    repository = payload.get("repository") or {}
    actor = run.get("actor") or run.get("triggering_actor") or {}
    head_commit = run.get("head_commit") or {}

    return {
        "repository": repository.get("full_name"),
        "workflow": run.get("name"),
        "branch": run.get("head_branch"),
        "trigger_event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "run_number": run.get("run_number"),
        "actor": actor.get("login"),
        "commit_message": head_commit.get("message"),
        "url": run.get("html_url"),
    }


async def _process_event(event_kind: str, payload: dict) -> None:
    """백그라운드에서 에이전트를 실행한다.

    백그라운드 태스크이므로 예외를 HTTP로 전달할 수 없다. 실패는 로그로만
    남기고 삼켜서 워커가 죽지 않도록 한다.
    """
    try:
        message = await run_noti_agent(event_kind, payload)
        logger.info("Noti processed (event_kind=%s): %s", event_kind, message)
    except (NotiAgentError, DiscordError):
        logger.exception("Noti processing failed (event_kind=%s)", event_kind)


@router.post("/github", response_model=NotiResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> NotiResponse:
    """GitHub Actions webhook을 수신해 완료된 워크플로 실행을 알림 처리한다."""
    body = await request.body()
    _verify_github_signature(body, x_hub_signature_256)

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="요청 본문이 유효한 JSON이 아닙니다.",
        )

    # GitHub이 webhook 등록 시 보내는 헬스체크 이벤트.
    if x_github_event == "ping":
        return NotiResponse(status="pong", detail="webhook 연결이 확인되었습니다.")

    if x_github_event != "workflow_run":
        return NotiResponse(
            status="ignored", detail=f"처리 대상이 아닌 이벤트입니다: {x_github_event}"
        )

    if payload.get("action") != _HANDLED_GITHUB_ACTION:
        return NotiResponse(
            status="ignored",
            detail=f"완료되지 않은 실행은 무시합니다: action={payload.get('action')}",
        )

    summary = _summarize_workflow_run(payload)
    background_tasks.add_task(_process_event, "github_workflow_run", summary)
    return NotiResponse(status="accepted", detail="워크플로 실행 알림을 처리 중입니다.")


@router.post("/alert", response_model=NotiResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_alert(
    payload: AlertPayload,
    background_tasks: BackgroundTasks,
) -> NotiResponse:
    """인프라 헬스 등 범용 모니터링 알림을 수신해 에이전트로 처리한다."""
    background_tasks.add_task(_process_event, "alert", payload.model_dump())
    return NotiResponse(status="accepted", detail="알림을 처리 중입니다.")
