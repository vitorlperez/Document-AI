"""Stripe settings (ADR-0023): off by default, both secrets required when on, live restricted keys in production."""

import logging
import re

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB = "postgresql+psycopg://test:test@localhost/test"
PROXY = {"auth_proxy_secret": "test-only-proxy-secret-at-least-32-chars", "auth_trusted_proxy_cidrs": "10.0.0.0/8"}
# Obviously fake values: long enough to spot in output, never shaped like a real key.
API_KEY = "rk_test_unit_only_value"
WEBHOOK_SECRET = "whsec_unit_only_value"
STRIPE_ENV = ("BILLING_PROVIDER", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_API_VERSION",
              "STRIPE_CHECKOUT_INTEGRATION_ID", "ENVIRONMENT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in STRIPE_ENV:
        monkeypatch.delenv(name, raising=False)


def stripe(**overrides) -> Settings:
    values = {"database_url": DB, "billing_provider": "stripe", "stripe_api_key": API_KEY,
              "stripe_webhook_secret": WEBHOOK_SECRET} | overrides
    return Settings(_env_file=None, **values)


class Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture()
def config_warnings():
    handler = Records()
    logger = logging.getLogger("document_intelligence.config")
    logger.addHandler(handler)
    yield handler.messages
    logger.removeHandler(handler)


def test_default_boots_without_any_stripe_setting():
    settings = Settings(_env_file=None, database_url=DB)
    assert settings.billing_provider == "none"
    assert settings.stripe_api_key is None and settings.stripe_webhook_secret is None
    assert settings.stripe_api_version == "2026-09-30.endive"
    assert re.fullmatch(r"arquivio_checkout_[a-z]{8}", settings.stripe_checkout_integration_id)


def test_settings_read_the_documented_environment_names(monkeypatch):
    monkeypatch.setenv("BILLING_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_API_KEY", API_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_API_VERSION", "2026-10-28.preview")
    monkeypatch.setenv("STRIPE_CHECKOUT_INTEGRATION_ID", "arquivio_checkout_override")
    settings = Settings(_env_file=None, database_url=DB)
    assert settings.stripe_api_key.get_secret_value() == API_KEY
    assert settings.stripe_webhook_secret.get_secret_value() == WEBHOOK_SECRET
    assert (settings.stripe_api_version, settings.stripe_checkout_integration_id) == (
        "2026-10-28.preview", "arquivio_checkout_override")


@pytest.mark.parametrize("missing,names", [
    ({"stripe_api_key": None}, "STRIPE_API_KEY"),
    ({"stripe_webhook_secret": None}, "STRIPE_WEBHOOK_SECRET"),
    ({"stripe_api_key": "  ", "stripe_webhook_secret": None}, "STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET"),
])
def test_stripe_provider_requires_both_secrets(missing, names):
    with pytest.raises(ValidationError, match=names) as error:
        stripe(**missing)
    assert API_KEY not in str(error.value) and WEBHOOK_SECRET not in str(error.value)


def test_provider_name_is_case_insensitive_for_the_secret_check():
    with pytest.raises(ValidationError, match="STRIPE_WEBHOOK_SECRET"):
        stripe(billing_provider=" Stripe ", stripe_webhook_secret=None)


def test_secrets_never_appear_in_repr_or_dumps():
    settings = stripe()
    for text in (repr(settings), str(settings), settings.model_dump_json(), repr(settings.model_dump())):
        assert API_KEY not in text and WEBHOOK_SECRET not in text


def test_development_accepts_test_mode_keys(config_warnings):
    assert stripe(stripe_api_key="sk_test_unit_only_value").environment == "development"
    assert config_warnings == []


@pytest.mark.parametrize("key", ["sk_test_unit_only_value", "rk_test_unit_only_value"])
def test_production_rejects_test_mode_keys(key):
    with pytest.raises(ValidationError, match="test-mode STRIPE_API_KEY") as error:
        stripe(environment="production", stripe_api_key=key, **PROXY)
    assert key not in str(error.value)


def test_production_warns_on_an_unrestricted_secret_key(config_warnings):
    stripe(environment="production", stripe_api_key="sk_live_unit_only_value", **PROXY)
    assert len(config_warnings) == 1 and "restricted key (rk_)" in config_warnings[0]
    assert "sk_live_unit_only_value" not in config_warnings[0]


def test_production_accepts_a_live_restricted_key_quietly(config_warnings):
    settings = stripe(environment="production", stripe_api_key="rk_live_unit_only_value", **PROXY)
    assert settings.billing_provider == "stripe" and config_warnings == []


def test_production_without_stripe_ignores_stripe_settings():
    settings = Settings(_env_file=None, database_url=DB, environment="production",
                        stripe_api_key="sk_test_unit_only_value", **PROXY)
    assert settings.billing_provider == "none"
