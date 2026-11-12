"""Settings loaded from environment variables (.env in development)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-3.5-flash",
    "openai": "gpt-4o-mini",
    "mock": "heuristic",
}
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# Tried in order when the main model is busy (free-tier models often return 503 at peak times).
GEMINI_FALLBACKS = ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest")
PROVIDERS = ("anthropic", "gemini", "openai", "mock")


@dataclass
class Settings:
    paypal_mode: str = "sandbox"          # sandbox | mock
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    llm_provider: str = ""                # anthropic | gemini | openai | mock ("" = pick from keys)
    llm_model: str = ""
    llm_fallback_models: List[str] = field(default_factory=list)
    llm_attempt_timeout: int = 40
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    job_price: str = "5.00"
    currency: str = "USD"
    max_attempts: int = 3
    data_dir: str = "data"
    max_upload_mb: int = 2
    max_rows: int = 5000
    warnings: List[str] = field(default_factory=list)

    def llm_key(self) -> str:
        return {"anthropic": self.anthropic_api_key, "gemini": self.gemini_api_key,
                "openai": self.openai_api_key}.get(self.llm_provider, "")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def load_settings(overrides: Optional[Dict] = None) -> Settings:
    s = Settings(
        paypal_mode=_env("PAYPAL_MODE", "sandbox").lower(),
        paypal_client_id=_env("PAYPAL_CLIENT_ID"),
        paypal_client_secret=_env("PAYPAL_CLIENT_SECRET"),
        paypal_base_url=_env("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        llm_provider=_env("LLM_PROVIDER").lower(),
        llm_model=_env("LLM_MODEL"),
        llm_fallback_models=[m.strip() for m in _env("LLM_FALLBACK_MODELS").split(",") if m.strip()],
        llm_attempt_timeout=int(_env("LLM_ATTEMPT_TIMEOUT", "40")),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        job_price=_env("JOB_PRICE", "5.00"),
        currency=_env("CURRENCY", "USD").upper(),
        max_attempts=int(_env("MAX_ATTEMPTS", "3")),
        data_dir=_env("DATA_DIR", "data"),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "2")),
        max_rows=int(_env("MAX_ROWS", "5000")),
    )
    for k, v in (overrides or {}).items():
        setattr(s, k, v)

    if "api-m.paypal.com" in s.paypal_base_url and "sandbox" not in s.paypal_base_url:
        raise RuntimeError("VoxProof is a hackathon prototype and only talks to the PayPal sandbox.")

    # ---- PayPal
    if s.paypal_mode not in ("sandbox", "mock"):
        s.warnings.append(f"Unknown PAYPAL_MODE '{s.paypal_mode}', using mock payments.")
        s.paypal_mode = "mock"
    if s.paypal_mode == "sandbox" and not (s.paypal_client_id and s.paypal_client_secret):
        s.warnings.append("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set: using MOCK payments. "
                          "Add sandbox keys (see docs/SETUP_KEYS.md) to use real PayPal.")
        s.paypal_mode = "mock"

    # ---- AI model: use the provider asked for, or the first one with a key
    if s.llm_provider and s.llm_provider not in PROVIDERS:
        s.warnings.append(f"Unknown LLM_PROVIDER '{s.llm_provider}'. Picking a provider from the keys you set.")
        s.llm_provider = ""
    if s.llm_provider and s.llm_provider != "mock" and not s.llm_key():
        s.warnings.append(f"LLM_PROVIDER={s.llm_provider} but its API key is empty. Picking a provider from the keys you set.")
        s.llm_provider = ""
    if not s.llm_provider:
        for name, key in (("anthropic", s.anthropic_api_key), ("gemini", s.gemini_api_key), ("openai", s.openai_api_key)):
            if key:
                s.llm_provider = name
                break
        else:
            s.llm_provider = "mock"
            s.warnings.append("No AI key set: using the offline heuristic drafter. Add GEMINI_API_KEY (free) "
                              "or ANTHROPIC_API_KEY (see docs/SETUP_KEYS.md) to use a real model.")
    if s.llm_provider == "gemini":
        s.openai_base_url = GEMINI_BASE_URL
        if not s.llm_fallback_models:
            s.llm_fallback_models = list(GEMINI_FALLBACKS)
    if not s.llm_model or s.llm_provider == "mock":
        s.llm_model = DEFAULT_MODELS[s.llm_provider]
    return s
