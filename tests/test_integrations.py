"""Checks the shape of real PayPal and LLM HTTP calls without network access."""
import json

import pytest

from app import llm as llm_module
from app import paypal as paypal_module
from app.config import load_settings
from app.main import create_app
from app.paypal import PayPalClient

from .conftest import REQUEST


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.content = b"" if payload is None else json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self):
        return self._payload


def test_paypal_calls(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(("POST", url, kw))
        return FakeResponse(200, {"access_token": "tok", "expires_in": 3600})

    def fake_request(method, url, **kw):
        calls.append((method, url, kw))
        if url.endswith("/void"):
            return FakeResponse(204)
        return FakeResponse(201, {"id": "X1", "status": "CREATED"})

    monkeypatch.setattr(paypal_module.requests, "post", fake_post)
    monkeypatch.setattr(paypal_module.requests, "request", fake_request)
    c = PayPalClient("id", "secret", "https://api-m.sandbox.paypal.com")
    c.create_order(amount="5.00", currency="USD", custom_id="h" * 64, reference_id="job", description="d")
    c.authorize_order("ORDER1", request_id="job-authorize")
    c.capture_authorization("AUTH1", request_id="job-capture")
    c.void_authorization("AUTH1", request_id="job-void")

    token_call = calls[0]
    assert token_call[1] == "https://api-m.sandbox.paypal.com/v1/oauth2/token"
    assert token_call[2]["data"] == {"grant_type": "client_credentials"}

    create = calls[1]
    body = json.loads(create[2]["data"])
    assert create[1].endswith("/v2/checkout/orders")
    assert body["intent"] == "AUTHORIZE"
    assert body["purchase_units"][0]["custom_id"] == "h" * 64
    assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "5.00"}

    assert calls[2][1].endswith("/v2/checkout/orders/ORDER1/authorize")
    assert calls[2][2]["headers"]["PayPal-Request-Id"] == "job-authorize"
    assert calls[3][1].endswith("/v2/payments/authorizations/AUTH1/capture")
    assert json.loads(calls[3][2]["data"]) == {"final_capture": True}
    assert calls[4][1].endswith("/v2/payments/authorizations/AUTH1/void")


def test_live_paypal_is_refused():
    with pytest.raises(RuntimeError):
        load_settings({"paypal_base_url": "https://api-m.paypal.com"})


@pytest.fixture
def ai_app(tmp_path, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    settings = load_settings({"paypal_mode": "mock", "llm_provider": "anthropic", "anthropic_api_key": "test-key",
                              "data_dir": str(tmp_path)})
    return create_app(settings)


def test_ai_contract_path_with_retry(ai_app, monkeypatch):
    """The model's first reply names a column that doesn't exist; the retry fixes it."""
    replies = [
        {"summary": "x", "mappings": [{"target": "sku", "source": "Item Number"}], "checks": []},
        {"summary": "Convert the catalog.", "mappings": [
            {"target": "sku", "source": "Item #"}, {"target": "title", "source": "Product Name"},
            {"target": "price", "source": "Unit Cost", "default": None}],
         "checks": [{"type": "no_invented_values", "targets": ["price"], "from_request": "Never invent missing prices"}],
         "assumptions": ["Unit Cost is the USD price."]},
    ]
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return FakeResponse(200, {"content": [{"type": "text", "text": __import__("json").dumps(replies[len(sent) - 1])}]})

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    client = ai_app.test_client()
    job = client.post("/api/jobs", data={"sample": "1"}).get_json()["job"]
    r = client.post(f"/api/jobs/{job['id']}/contract", json={"request_text": REQUEST})
    assert r.status_code == 200, r.get_json()
    contract = r.get_json()["job"]["contract"]
    assert len(sent) == 2 and "failed validation" in sent[1]["messages"][0]["content"]
    assert sent[0]["model"] and sent[0]["system"].startswith("You are the contract drafter")
    assert contract["drafted_by"].startswith("anthropic/")
    assert any(c["origin"] == "customer" and c["type"] == "no_invented_values" for c in contract["checks"])
    assert any(c["type"] == "ids_preserved" for c in contract["checks"])  # added as protection
    assert contract["price"]["amount"] == "5.00"


def test_gemini_request_shape(monkeypatch):
    from app.llm import LLMClient
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return FakeResponse(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(llm_module.requests, "post", fake_post)
    s = load_settings({"llm_provider": "gemini", "gemini_api_key": "gkey", "paypal_mode": "mock"})
    out = LLMClient(s).complete_json("sys", "user")
    assert out == {"ok": True}
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer gkey"
    assert seen["body"]["response_format"] == {"type": "json_object"}
