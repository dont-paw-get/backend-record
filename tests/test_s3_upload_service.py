"""app/services/s3_upload.py 단위 테스트.

실제 AWS S3를 호출하지 않고 Mock Client를 사용하여 object key 생성,
put_object 호출 인자, ACL 미지정, 오류 매핑을 검증한다.
"""
import asyncio
from unittest.mock import MagicMock

import botocore.exceptions
import pytest

from app.core.config import settings
from app.services import s3_upload


def _run(coro):
    return asyncio.run(coro)


def test_upload_jpeg_generates_uuid_key_with_jpg_extension():
    fake_client = MagicMock()

    object_key = _run(
        s3_upload.upload_scrap_image(
            b"fake-jpeg-bytes", "image/jpeg", client=fake_client
        )
    )

    assert object_key.startswith("scraps/")
    assert object_key.endswith(".jpg")
    # "scraps/" + 36자 UUID + ".jpg"
    uuid_part = object_key[len("scraps/") : -len(".jpg")]
    assert len(uuid_part) == 36


def test_upload_png_generates_uuid_key_with_png_extension():
    fake_client = MagicMock()

    object_key = _run(
        s3_upload.upload_scrap_image(
            b"fake-png-bytes", "image/png", client=fake_client
        )
    )

    assert object_key.startswith("scraps/")
    assert object_key.endswith(".png")


def test_put_object_called_with_expected_arguments():
    fake_client = MagicMock()

    object_key = _run(
        s3_upload.upload_scrap_image(
            b"fake-jpeg-bytes", "image/jpeg", client=fake_client
        )
    )

    fake_client.put_object.assert_called_once()
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == settings.SCRAP_S3_BUCKET
    assert kwargs["Key"] == object_key
    assert kwargs["Body"] == b"fake-jpeg-bytes"
    assert kwargs["ContentType"] == "image/jpeg"


def test_put_object_never_receives_acl():
    fake_client = MagicMock()

    _run(
        s3_upload.upload_scrap_image(
            b"fake-jpeg-bytes", "image/jpeg", client=fake_client
        )
    )

    kwargs = fake_client.put_object.call_args.kwargs
    assert "ACL" not in kwargs


def test_s3_client_error_raises_application_exception():
    fake_client = MagicMock()
    fake_client.put_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
    )

    with pytest.raises(s3_upload.S3UploadRequestFailedError):
        _run(
            s3_upload.upload_scrap_image(
                b"fake-jpeg-bytes", "image/jpeg", client=fake_client
            )
        )


def test_unsupported_content_type_rejected_without_calling_s3():
    fake_client = MagicMock()

    with pytest.raises(s3_upload.UnsupportedImageContentTypeError):
        _run(
            s3_upload.upload_scrap_image(
                b"fake-bytes", "image/gif", client=fake_client
            )
        )

    fake_client.put_object.assert_not_called()


def test_original_filename_is_never_used_as_key():
    """사용자가 보낸 원본 filename을 넘겨도(인자로 받지 않으므로) key에 반영될 수 없다."""
    fake_client = MagicMock()

    object_key = _run(
        s3_upload.upload_scrap_image(
            b"fake-jpeg-bytes", "image/jpeg", client=fake_client
        )
    )

    assert "../" not in object_key
    assert object_key.count("/") == 1
    assert object_key.split("/")[1] != ""
