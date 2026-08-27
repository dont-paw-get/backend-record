"""app/core/config.py의 CLOVA_OCR_* 환경변수 설정에 대한 단위 테스트.

DATABASE_URL 정책(CLIAR-39)과 동일하게 CLOVA_OCR_INVOKE_URL,
CLOVA_OCR_SECRET_KEY도 기본값이 없는 필수 환경변수로 요구된다.
"""
import importlib
import sys

import pytest
from pydantic import ValidationError

VALID_ENV = {
    "DATABASE_URL": "postgresql+psycopg://test_user:test_password@localhost:5433/test_db",
    "CLOVA_OCR_INVOKE_URL": "https://example.apigw.ntruss.com/custom/v1/00000/xxxxxxxx/general",
    "CLOVA_OCR_SECRET_KEY": "dummy-test-secret-key",
}


def _reload_config(monkeypatch, overrides=None):
    env = {**VALID_ENV, **(overrides or {})}
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("app.core.config", None)
    return importlib.import_module("app.core.config")


def test_settings_reads_clova_ocr_env_vars(monkeypatch):
    config_module = _reload_config(monkeypatch)

    assert config_module.settings.CLOVA_OCR_INVOKE_URL == VALID_ENV["CLOVA_OCR_INVOKE_URL"]
    assert config_module.settings.CLOVA_OCR_SECRET_KEY == VALID_ENV["CLOVA_OCR_SECRET_KEY"]


def test_settings_requires_clova_ocr_invoke_url(monkeypatch):
    config_module = _reload_config(monkeypatch)
    monkeypatch.delenv("CLOVA_OCR_INVOKE_URL", raising=False)

    with pytest.raises(ValidationError):
        config_module.Settings(_env_file=None)


def test_settings_requires_clova_ocr_secret_key(monkeypatch):
    config_module = _reload_config(monkeypatch)
    monkeypatch.delenv("CLOVA_OCR_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        config_module.Settings(_env_file=None)


def test_settings_bedrock_defaults_and_overrides(monkeypatch):
    config_module = _reload_config(monkeypatch)
    assert config_module.settings.OCR_PROVIDER == "clova"
    assert config_module.settings.AWS_REGION == "us-east-1"
    assert config_module.settings.BEDROCK_OCR_MODEL_ID == "qwen.qwen3-vl-235b-a22b"

    config_module_custom = _reload_config(
        monkeypatch,
        overrides={
            "OCR_PROVIDER": "bedrock",
            "AWS_REGION": "ap-northeast-2",
            "BEDROCK_OCR_MODEL_ID": "custom-model",
            "AWS_PROFILE": "kosa-mfa",
        },
    )
    assert config_module_custom.settings.OCR_PROVIDER == "bedrock"
    assert config_module_custom.settings.AWS_REGION == "ap-northeast-2"
    assert config_module_custom.settings.BEDROCK_OCR_MODEL_ID == "custom-model"
    assert config_module_custom.settings.AWS_PROFILE == "kosa-mfa"
