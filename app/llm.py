"""Minimal LLM clients that return JSON.

Supports Anthropic (Claude), Google Gemini (free tier, via its OpenAI-compatible
endpoint) and any OpenAI-compatible chat-completions API (OpenAI, Groq,
OpenRouter, Ollama...).
`mock` is an offline fallback: callers use deterministic heuristics instead.
"""
from __future__ import annotations

import json
import re
from typing import Dict

import requests

from .config import Settings


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("Model reply did not contain a JSON object.")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"Model reply was not valid JSON: {e}") from e


class LLMClient:
    def __init__(self, settings: Settings):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.settings = settings
        self.timeout = 90
        self.attempt_timeout = settings.llm_attempt_timeout
        self.last_model = self.model

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    @property
    def label(self) -> str:
        return "offline heuristic (no AI key set)" if self.is_mock else f"{self.provider}/{self.model}"

    def complete_json(self, system: str, user: str, max_tokens: int = 2000) -> Dict:
        if self.is_mock:
            raise LLMError("Mock provider has no model; callers must use heuristics.")
        if self.provider == "anthropic":
            text = self._anthropic(system, user, max_tokens)
        else:
            text = self._openai(system, user, max_tokens)
        return extract_json(text)

    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise LLMError(f"Could not reach Anthropic: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"Anthropic error {r.status_code}: {r.text[:300]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def _models_to_try(self):
        models = [self.model] + [m for m in self.settings.llm_fallback_models if m != self.model]
        return models

    def _openai(self, system: str, user: str, max_tokens: int) -> str:
        """OpenAI-compatible chat completions (OpenAI, Gemini, Groq, OpenRouter, Ollama...).

        If a model is overloaded (429/5xx) or too slow, the next model in
        LLM_FALLBACK_MODELS is tried, so a busy free-tier model doesn't break the demo.
        """
        url = f"{self.settings.openai_base_url}/chat/completions"
        key = self.settings.gemini_api_key if self.provider == "gemini" else self.settings.openai_api_key
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        errors = []
        for model in self._models_to_try():
            body = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max(max_tokens, 4000),
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            if self.provider == "gemini":
                body["reasoning_effort"] = "low"
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.attempt_timeout)
                if r.status_code == 400:
                    # Some models reject optional parameters; retry once without them.
                    for optional in ("response_format", "reasoning_effort", "temperature"):
                        body.pop(optional, None)
                    r = requests.post(url, headers=headers, json=body, timeout=self.attempt_timeout)
            except requests.Timeout:
                errors.append(f"{model}: timed out after {self.attempt_timeout}s")
                continue
            except requests.RequestException as e:
                raise LLMError(f"Could not reach the model API: {e}") from e
            if r.status_code in (429, 500, 502, 503, 504):
                errors.append(f"{model}: busy ({r.status_code})")
                continue
            if r.status_code >= 400:
                raise LLMError(f"Model API error {r.status_code} for {model}: {r.text[:300]}")
            self.last_model = model
            return r.json()["choices"][0]["message"]["content"] or ""
        raise LLMError("All models were busy or too slow: " + "; ".join(errors)
                       + ". Try again in a minute, or set LLM_MODEL / LLM_FALLBACK_MODELS in .env.")


def ask_json_with_retry(llm: LLMClient, system: str, user: str, validate, max_tokens: int = 2000):
    """Call the model, validate, and retry once with the validation error."""
    first = llm.complete_json(system, user, max_tokens)
    try:
        return validate(first)
    except ValueError as e:
        retry_user = (user + "\n\nYour previous reply failed validation: " + str(e)
                      + "\nPrevious reply:\n" + json.dumps(first)[:4000]
                      + "\nReply with corrected JSON only.")
        second = llm.complete_json(system, retry_user, max_tokens)
        return validate(second)
