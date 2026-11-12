"""PayPal Orders v2 + Payments v2 client (sandbox), and an offline mock.

Flow used by VoxProof:
  1. create_order(intent=AUTHORIZE, custom_id=<contract sha256>)
  2. buyer approves in the PayPal popup (JS SDK, intent=authorize)
  3. authorize_order  -> authorization id (funds on hold, not captured)
  4. capture_authorization  (checks passed + customer tapped Accept)
     or void_authorization  (checks failed, customer rejected, or gave up)

Only this module holds PayPal credentials, and only the /accept route in
main.py calls capture_authorization.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests

from .config import Settings


class PayPalError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, debug_id: Optional[str] = None,
                 details: Optional[list] = None):
        super().__init__(message)
        self.status = status
        self.debug_id = debug_id
        self.details = details or []


def first_authorization(order: Dict) -> Dict:
    try:
        return order["purchase_units"][0]["payments"]["authorizations"][0]
    except (KeyError, IndexError, TypeError):
        raise PayPalError("PayPal did not return an authorization for this order.")


class PayPalClient:
    is_mock = False

    def __init__(self, client_id: str, client_secret: str, base_url: str, timeout: int = 30):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            try:
                r = requests.post(f"{self.base_url}/v1/oauth2/token",
                                  auth=(self.client_id, self.client_secret),
                                  data={"grant_type": "client_credentials"},
                                  headers={"Accept": "application/json"}, timeout=self.timeout)
            except requests.RequestException as e:
                raise PayPalError(f"Could not reach PayPal: {e}") from e
            if r.status_code != 200:
                raise PayPalError(f"PayPal auth failed ({r.status_code}). Check PAYPAL_CLIENT_ID / SECRET.", r.status_code)
            data = r.json()
            self._token = data["access_token"]
            self._token_expiry = time.time() + int(data.get("expires_in", 3000))
            return self._token

    def _call(self, method: str, path: str, body: Optional[Dict] = None, request_id: Optional[str] = None) -> Dict:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            r = requests.request(method, f"{self.base_url}{path}", headers=headers,
                                 data=json.dumps(body) if body is not None else None, timeout=self.timeout)
        except requests.RequestException as e:
            raise PayPalError(f"Could not reach PayPal: {e}") from e
        if r.status_code >= 400:
            try:
                err = r.json()
            except ValueError:
                err = {"message": r.text[:300]}
            issue = ""
            if err.get("details"):
                issue = " " + "; ".join(f"{d.get('issue')}: {d.get('description', '')}" for d in err["details"])
            raise PayPalError(f"PayPal {err.get('name', 'error')}: {err.get('message', '')}{issue}",
                              r.status_code, err.get("debug_id"), err.get("details"))
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    # -- Orders v2 ----------------------------------------------------------
    def create_order(self, *, amount: str, currency: str, custom_id: str, reference_id: str, description: str) -> Dict:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [{
                "reference_id": reference_id[:256],
                "custom_id": custom_id[:127],
                "description": description[:127],
                "amount": {"currency_code": currency, "value": amount},
            }],
        }
        return self._call("POST", "/v2/checkout/orders", body, request_id=f"order-{uuid.uuid4()}")

    def get_order(self, order_id: str) -> Dict:
        return self._call("GET", f"/v2/checkout/orders/{order_id}")

    def authorize_order(self, order_id: str, request_id: str) -> Dict:
        return self._call("POST", f"/v2/checkout/orders/{order_id}/authorize", {}, request_id=request_id)

    # -- Payments v2 --------------------------------------------------------
    def get_authorization(self, authorization_id: str) -> Dict:
        return self._call("GET", f"/v2/payments/authorizations/{authorization_id}")

    def capture_authorization(self, authorization_id: str, request_id: str) -> Dict:
        return self._call("POST", f"/v2/payments/authorizations/{authorization_id}/capture",
                          {"final_capture": True}, request_id=request_id)

    def void_authorization(self, authorization_id: str, request_id: str) -> Dict:
        return self._call("POST", f"/v2/payments/authorizations/{authorization_id}/void", None, request_id=request_id)


class MockPayPal:
    """Offline stand-in with the same interface. State lives in a JSON file so
    it survives Flask's auto-reloader. Never used when sandbox keys are set."""
    is_mock = True

    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "mock_paypal.json")
        self._lock = threading.Lock()

    def _load(self) -> Dict:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {"orders": {}, "auths": {}}

    def _save(self, db: Dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f)
        os.replace(tmp, self.path)

    def create_order(self, *, amount, currency, custom_id, reference_id, description) -> Dict:
        with self._lock:
            db = self._load()
            oid = "MOCK-ORDER-" + uuid.uuid4().hex[:10].upper()
            order = {"id": oid, "status": "CREATED", "intent": "AUTHORIZE",
                     "purchase_units": [{"reference_id": reference_id, "custom_id": custom_id,
                                         "description": description,
                                         "amount": {"currency_code": currency, "value": amount}}]}
            db["orders"][oid] = order
            self._save(db)
            return order

    def get_order(self, order_id: str) -> Dict:
        db = self._load()
        if order_id not in db["orders"]:
            raise PayPalError("Order not found", 404)
        return db["orders"][order_id]

    def authorize_order(self, order_id: str, request_id: str) -> Dict:
        with self._lock:
            db = self._load()
            order = db["orders"].get(order_id)
            if not order:
                raise PayPalError("Order not found", 404)
            if order["status"] == "COMPLETED":
                return order
            unit = order["purchase_units"][0]
            aid = "MOCK-AUTH-" + uuid.uuid4().hex[:10].upper()
            expires = (datetime.now(timezone.utc) + timedelta(days=29)).isoformat(timespec="seconds")
            auth = {"id": aid, "status": "CREATED", "amount": unit["amount"], "custom_id": unit["custom_id"],
                    "expiration_time": expires}
            unit["payments"] = {"authorizations": [auth]}
            order["status"] = "COMPLETED"
            db["auths"][aid] = auth
            self._save(db)
            return order

    def get_authorization(self, authorization_id: str) -> Dict:
        db = self._load()
        if authorization_id not in db["auths"]:
            raise PayPalError("Authorization not found", 404)
        return db["auths"][authorization_id]

    def capture_authorization(self, authorization_id: str, request_id: str) -> Dict:
        with self._lock:
            db = self._load()
            auth = db["auths"].get(authorization_id)
            if not auth:
                raise PayPalError("Authorization not found", 404)
            if auth["status"] == "VOIDED":
                raise PayPalError("AUTHORIZATION_VOIDED: authorization was voided", 422)
            auth["status"] = "CAPTURED"
            capture = {"id": "MOCK-CAPTURE-" + uuid.uuid4().hex[:10].upper(), "status": "COMPLETED",
                       "amount": auth["amount"], "final_capture": True}
            auth["capture"] = capture
            self._save(db)
            return capture

    def void_authorization(self, authorization_id: str, request_id: str) -> Dict:
        with self._lock:
            db = self._load()
            auth = db["auths"].get(authorization_id)
            if not auth:
                raise PayPalError("Authorization not found", 404)
            if auth["status"] == "CAPTURED":
                raise PayPalError("AUTHORIZATION_ALREADY_CAPTURED", 422)
            auth["status"] = "VOIDED"
            self._save(db)
            return {"id": authorization_id, "status": "VOIDED"}


def get_paypal(settings: Settings):
    if settings.paypal_mode == "mock":
        return MockPayPal(settings.data_dir)
    return PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url)
