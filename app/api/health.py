from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def get_health() -> dict:
    """서비스 상태 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
