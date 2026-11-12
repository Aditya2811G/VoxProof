"""Checks that your .env keys work before you run the demo.

    python check_setup.py

It (1) gets a PayPal sandbox access token, (2) creates a test order with
intent AUTHORIZE (never approved, so no money moves; it simply expires),
and (3) asks your AI model for a tiny JSON reply.
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import load_settings  # noqa: E402
from app.llm import LLMClient, LLMError  # noqa: E402
from app.paypal import PayPalClient, PayPalError  # noqa: E402

OK, BAD, WARN = "[ OK ]", "[FAIL]", "[WARN]"


def check_paypal(s) -> bool:
    print("\nPayPal")
    if s.paypal_mode == "mock":
        print(f"{WARN} PayPal is in MOCK mode. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env "
              "(docs/SETUP_KEYS.md, step 1) for real sandbox payments.")
        return False
    client = PayPalClient(s.paypal_client_id, s.paypal_client_secret, s.paypal_base_url)
    try:
        client._access_token()
        print(f"{OK} Sandbox access token received.")
    except PayPalError as e:
        print(f"{BAD} {e}")
        if "Could not reach" in str(e):
            print("       Fix: check your internet connection, VPN or firewall.")
        else:
            print("       Fix: copy the Client ID and Secret again from developer.paypal.com > Apps & Credentials, "
                  "with the toggle on Sandbox. No spaces or quotes in .env.")
        return False
    try:
        order = client.create_order(amount=s.job_price, currency=s.currency, custom_id="setup-check",
                                    reference_id="setup-check", description="VoxProof setup check")
        print(f"{OK} Test order {order['id']} created with intent AUTHORIZE ({s.job_price} {s.currency}). "
              "It is never approved, so nothing is charged.")
    except PayPalError as e:
        print(f"{BAD} Could not create an AUTHORIZE order: {e}")
        print("       Fix: link your app to a United States sandbox Business account (docs/SETUP_KEYS.md, step 1).")
        return False
    print(f"{OK} Client ID for the browser buttons: {s.paypal_client_id[:12]}...")
    return True


def check_ai(s) -> bool:
    print("\nAI model")
    llm = LLMClient(s)
    if llm.is_mock:
        print(f"{WARN} No AI key: using the offline heuristic. Set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY "
              "(docs/SETUP_KEYS.md, step 2).")
        return False
    try:
        reply = llm.complete_json('Reply with JSON only: {"ok": true}', "Health check.", max_tokens=50)
    except LLMError as e:
        print(f"{BAD} {llm.label}: {e}")
        print("       Fix: check the key, and set LLM_MODEL to a model your account can use.")
        return False
    print(f"{OK} {llm.provider}/{llm.last_model} replied: {reply}")
    if llm.last_model != llm.model:
        print(f"{WARN} {llm.model} was busy, so the backup model {llm.last_model} answered. "
              f"Consider LLM_MODEL={llm.last_model} in .env.")
    return True


def main() -> int:
    try:
        s = load_settings()
    except RuntimeError as e:
        print(f"{BAD} {e}")
        return 1
    for w in s.warnings:
        print(f"{WARN} {w}")
    paypal_ok = check_paypal(s)
    ai_ok = check_ai(s)
    print()
    if paypal_ok and ai_ok:
        print("All set. Run:  python run.py   and open http://localhost:8000")
        return 0
    print("Not ready for the real demo yet (mock mode still works for practice).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
