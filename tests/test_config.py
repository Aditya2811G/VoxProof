import pytest

from app.config import GEMINI_BASE_URL, load_settings

KEYS = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
        "LLM_PROVIDER", "LLM_MODEL", "PAYPAL_MODE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_no_keys_means_mock_everything():
    s = load_settings()
    assert s.paypal_mode == "mock" and s.llm_provider == "mock"
    assert len(s.warnings) == 2


def test_gemini_key_alone_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    s = load_settings()
    assert s.llm_provider == "gemini"
    assert s.openai_base_url == GEMINI_BASE_URL
    assert s.llm_model


def test_explicit_provider_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    s = load_settings()
    assert s.llm_provider == "openai"


def test_sandbox_keys_enable_sandbox(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    assert load_settings().paypal_mode == "sandbox"
