"""스크랩 이미지 S3 업로드 서비스.

RECORD-1: OCR endpoint와의 연결(RECORD-2에서 진행) 없이, S3에 안전하게
업로드할 수 있는 내부 서비스 기반만 제공한다. IAM 정책이 s3:PutObject만
허용하므로 이 모듈도 PutObject 외의 S3 API는 호출하지 않는다.
"""
import asyncio
import logging
import threading
import uuid

import boto3
import botocore.exceptions

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3UploadError(Exception):
    """S3 업로드 관련 오류의 베이스 클래스."""


class UnsupportedImageContentTypeError(S3UploadError):
    """지원하지 않는 이미지 Content-Type인 경우."""


class S3UploadRequestFailedError(S3UploadError):
    """S3 PutObject 호출이 실패한 경우."""


# 현재 OCR 엔드포인트(app/api/ocr.py: SUPPORTED_CONTENT_TYPES)가 허용하는
# 이미지 형식과 동일하게 유지한다. 이 서비스는 API 계층에 의존하지 않도록
# 별도로 정의하되, 두 목록은 항상 같은 형식 집합을 가리켜야 한다.
_CONTENT_TYPE_TO_EXTENSION = {
    "image/jpeg": "jpg",
    "image/png": "png",
}

_SCRAP_KEY_PREFIX = "scraps"


def get_s3_client():
    """boto3 Default Credential Provider Chain(IRSA 포함)으로 S3 클라이언트를 생성한다.

    static credential을 하드코딩하지 않는다. 환경변수(AWS_ACCESS_KEY_ID 등)나
    profile이 설정에 명시된 경우에만 boto3.Session에 전달하며, 그 외에는
    boto3 기본 Credential Provider Chain(EKS Pod의 경우 ServiceAccount IRSA)에
    맡긴다.
    """
    session_kwargs = {}
    if settings.AWS_PROFILE:
        session_kwargs["profile_name"] = settings.AWS_PROFILE
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.AWS_SESSION_TOKEN:
            session_kwargs["aws_session_token"] = settings.AWS_SESSION_TOKEN

    session = boto3.Session(**session_kwargs)
    return session.client("s3", region_name=settings.AWS_REGION)


# boto3 클라이언트 생성은 서비스 모델 로딩 + 자격증명 체인 해석(IRSA 시 네트워크
# 조회 포함)이 있어 요청당 오버헤드가 크다. 저수준 boto3 클라이언트는 메서드
# 호출에 대해 thread-safe 하므로 한 번 만들어 모든 업로드가 재사용한다.
_cached_s3_client = None
_s3_client_lock = threading.Lock()


def _get_cached_s3_client():
    """프로세스 전역에서 재사용하는 S3 클라이언트를 반환한다."""
    global _cached_s3_client
    if _cached_s3_client is None:
        with _s3_client_lock:
            if _cached_s3_client is None:
                _cached_s3_client = get_s3_client()
    return _cached_s3_client


def _resolve_extension(content_type: str) -> str:
    try:
        return _CONTENT_TYPE_TO_EXTENSION[content_type]
    except KeyError as exc:
        raise UnsupportedImageContentTypeError(
            f"지원하지 않는 이미지 형식입니다: {content_type}"
        ) from exc


def _sync_upload_scrap_image(image_bytes: bytes, content_type: str, client=None) -> str:
    """동기적으로 S3 PutObject를 호출해 스크랩 이미지를 업로드한다."""
    extension = _resolve_extension(content_type)
    object_key = f"{_SCRAP_KEY_PREFIX}/{uuid.uuid4()}.{extension}"

    s3_client = client or _get_cached_s3_client()

    try:
        # 버킷이 Private이므로 ACL은 지정하지 않는다. IAM 정책이 PutObject만
        # 허용하므로 이 호출 외의 S3 API(ListBucket/GetObject 등)는 사용하지 않는다.
        s3_client.put_object(
            Bucket=settings.SCRAP_S3_BUCKET,
            Key=object_key,
            Body=image_bytes,
            ContentType=content_type,
        )
    except botocore.exceptions.ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        logger.warning(
            "Scrap image S3 upload failed with %s (key=%s)",
            error_code,
            object_key,
        )
        raise S3UploadRequestFailedError(f"S3 upload failed: {error_code}") from exc
    except Exception as exc:
        logger.warning(
            "Scrap image S3 upload failed unexpectedly: %s (key=%s)",
            type(exc).__name__,
            object_key,
        )
        raise S3UploadRequestFailedError("S3 upload failed") from exc

    logger.info("Scrap image uploaded to S3 (key=%s)", object_key)
    return object_key


async def upload_scrap_image(image_bytes: bytes, content_type: str, client=None) -> str:
    """
    스크랩 이미지를 S3(settings.SCRAP_S3_BUCKET)에 업로드하고 object key를 반환한다.
    """
    return await asyncio.to_thread(
        _sync_upload_scrap_image, image_bytes, content_type, client
    )


def build_cloudfront_url(object_key: str) -> str:
    """
    S3 object key로부터 스크랩 이미지의 CloudFront URL을 생성한다.
    """
    return f"https://{settings.SCRAP_CLOUDFRONT_DOMAIN}/{object_key}"
