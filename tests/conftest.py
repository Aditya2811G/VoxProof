import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

REQUEST = "Convert this into my store's import format. Preserve all product IDs. Never invent missing prices."


@pytest.fixture
def app(tmp_path, monkeypatch):
    for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings({"paypal_mode": "mock", "llm_provider": "mock", "data_dir": str(tmp_path)})
    return create_app(settings)


@pytest.fixture
def client(app):
    return app.test_client()


def start_job(client, request_text=REQUEST):
    job = client.post("/api/jobs", data={"sample": "1"}).get_json()["job"]
    job = client.post(f"/api/jobs/{job['id']}/contract", json={"request_text": request_text}).get_json()["job"]
    return job


def authorized_job(client, request_text=REQUEST):
    job = start_job(client, request_text)
    jid = job["id"]
    client.post(f"/api/jobs/{jid}/agree", json={"contract_sha256": job["contract_sha256"]})
    order_id = client.post(f"/api/jobs/{jid}/paypal/order").get_json()["id"]
    return client.post(f"/api/jobs/{jid}/paypal/authorize", json={"order_id": order_id}).get_json()["job"]
