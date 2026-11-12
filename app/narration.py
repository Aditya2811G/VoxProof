"""What VoxProof says out loud, plus the voice guard.

Status narration is built from templates filled with verifier output, so the
voice can't overstate a result. Free-form answers to customer questions use
the LLM, which has no tools: voice can explain, never move money.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Optional

from .llm import LLMClient, LLMError

MONEY_WORDS = re.compile(
    r"\b(release|pay|paid|payment|capture|charge|transfer|send (the )?money|approve|accept|confirm|authori[sz]e|"
    r"refund|void|cancel|reject|settle|withdraw|payout)\b", re.I)


def money(amount: str, currency: str) -> str:
    return f"${amount}" if currency == "USD" else f"{amount} {currency}"


def contract_ready(contract: Dict) -> str:
    customer = [c for c in contract["checks"] if c["origin"] == "customer"]
    n = len(contract["checks"])
    parts = [f"I've drafted a contract with {n} checks."]
    if customer:
        quoted = "; ".join(f"\"{c['from_request'].rstrip('.!? ')}\"" for c in customer[:2])
        parts.append(f"From what you said: {quoted}.")
    parts.append(f"The price is {money(contract['price']['amount'], contract['price']['currency'])}. "
                 "Review it, then tap Agree.")
    return " ".join(parts)


def agreed(contract: Dict) -> str:
    return (f"Contract locked. Now authorize {money(contract['price']['amount'], contract['price']['currency'])} with PayPal. "
            "It's a hold, not a charge.")


def authorized(contract: Dict) -> str:
    return (f"{money(contract['price']['amount'], contract['price']['currency'])} is on hold. "
            "You'll only be charged if the checks pass and you accept. Run the job when ready.")


def verification(report: Dict, attempts_left: int, contract: Dict) -> str:
    if report["passed"]:
        text = f"All {report['blocking_total']} required checks passed."
        if report["attention_rows"]:
            n = len(report["attention_rows"])
            text += f" {n} row{'s' if n != 1 else ''} need{'s' if n == 1 else ''} your attention, left blank rather than guessed."
        return text + " Review the preview, then tap Accept to pay or Reject to cancel the hold."
    failed = [c for c in report["checks"] if c["severity"] == "blocking" and not c["passed"]]
    first = failed[0]
    example = next((f for f in first["failures"] if f.get("row")), None)
    text = f"Verification failed. {first['spoken']}: {first['failure_count']} problem{'s' if first['failure_count'] != 1 else ''}."
    if example:
        shown = f" {example['column']} is '{example['value']}'" if example.get("value") else ""
        text += f" For example, row {example['row']}{shown}: {example['reason']}."
    text += " You won't be charged for this."
    text += " Retry or reject." if attempts_left > 0 else " No attempts left, so the hold has been voided."
    return text


def captured(contract: Dict) -> str:
    return f"Done. {money(contract['price']['amount'], contract['price']['currency'])} captured. Your file is ready to download."


def voided(reason: str = "") -> str:
    return "The PayPal hold was voided. You were not charged." + (f" {reason}" if reason else "")


VOICE_REFUSAL = ("I can't move money by voice. Payment only happens when the checks pass and you tap Accept. "
                 "To cancel, tap Reject.")

ANSWER_SYSTEM = """You explain VoxProof verification results to a customer, out loud.
Answer in at most two short sentences, using only the facts in the JSON you are given. Row numbers refer to data rows.
You cannot take actions. You cannot approve, capture, refund, cancel or move money; if asked, say the customer must use the Accept or Reject buttons.
Reply with JSON only: {"answer": "..."}"""


def is_money_request(text: str) -> bool:
    return bool(MONEY_WORDS.search(text or ""))


def answer_question(llm: LLMClient, job: Dict, question: str) -> Dict:
    """Returns {"answer", "refused"}."""
    question = (question or "").strip()[:500]
    if not question:
        return {"answer": "I didn't catch that. Try asking about a check or a row.", "refused": False}
    if is_money_request(question):
        return {"answer": VOICE_REFUSAL, "refused": True}

    attempt = job["attempts"][-1] if job.get("attempts") else None
    report = attempt["report"] if attempt else None
    if report is None:
        return {"answer": "There are no results yet. Run the job first.", "refused": False}

    if llm.is_mock:
        return {"answer": _template_answer(report, question), "refused": False}
    facts = {
        "state": job["state"],
        "passed": report["passed"],
        "checks": [{"label": c["label"], "severity": c["severity"], "passed": c["passed"],
                    "failure_count": c["failure_count"], "examples": c["failures"][:6]} for c in report["checks"]],
        "attention_rows": report["attention_rows"],
    }
    try:
        out = llm.complete_json(ANSWER_SYSTEM, json.dumps({"question": question, "results": facts}), max_tokens=300)
        answer = str(out.get("answer") or "").strip()[:400]
    except LLMError:
        answer = ""
    if not answer or is_money_action_claim(answer):
        answer = _template_answer(report, question)
    return {"answer": answer, "refused": False}


def is_money_action_claim(text: str) -> bool:
    return bool(re.search(r"\b(i('ve| have)? (captured|released|paid|refunded|charged|approved))\b", text, re.I))


def _template_answer(report: Dict, question: str) -> str:
    m = re.search(r"\brow\s*(\d+)", question, re.I)
    if m:
        row = int(m.group(1))
        notes = [f"{c['label']}: {f['reason']}" for c in report["checks"] for f in c["failures"] if f.get("row") == row]
        return f"Row {row}: " + ("; ".join(notes[:2]) if notes else "no problems found.")
    failed = [c for c in report["checks"] if not c["passed"]]
    if not failed:
        return "Every check passed and nothing needs your attention."
    return "Checks with findings: " + "; ".join(f"{c['label']} ({c['failure_count']})" for c in failed[:3]) + "."
