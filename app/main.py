"""VoxProof HTTP API (Flask).

Money moves in exactly two places:
  * /accept  -> capture, only if the verifier passed (re-checked here), the
                output file is unchanged, the PayPal order is bound to this
                contract's hash, and the customer tapped Accept.
  * _void()  -> void, when checks fail for good or the customer rejects.
No voice or AI code path can reach either.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from . import narration
from .config import Settings, load_settings
from .checks import CHECK_LIBRARY
from .contract import ContractError, contract_hash, draft_contract
from .csvio import CSVFormatError, decode_upload, parse_csv_text, read_csv, sha256_file, write_csv
from .executor import PlanError, execute, validate_plan
from .llm import LLMClient, LLMError
from .paypal import PayPalError, first_authorization, get_paypal
from .schema import load_schema
from .store import (AGREED, AUTHORIZED, CAPTURED, CONTRACT_PROPOSED, EXPIRED, UPLOADED, VERIFIED_FAIL,
                    VERIFIED_PASS, VOIDED, JobStore, StateError)
from .verifier import verify_files
from .worker import feedback_from_report, heuristic_plan, inject_fault, plan_operations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT, "static")
SAMPLE_PATH = os.path.join(ROOT, "samples", "supplier_catalog_messy.csv")


class APIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024

    store = JobStore(settings.data_dir)
    llm = LLMClient(settings)
    paypal = get_paypal(settings)
    schema = load_schema()
    locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
    locks_guard = threading.Lock()
    app.extensions["voxproof"] = {"settings": settings, "store": store, "llm": llm, "paypal": paypal}

    for w in settings.warnings:
        app.logger.warning(w)

    # ------------------------------------------------------------------ utils
    def job_lock(job_id: str) -> threading.Lock:
        with locks_guard:
            return locks[job_id]

    def load(job_id: str) -> Dict:
        job = store.get(job_id)
        if not job:
            raise APIError("Job not found.", 404)
        return job

    def require(job: Dict, *states: str) -> None:
        if job["state"] not in states:
            raise APIError(f"This step isn't available while the job is {job['state']}.", 409)

    def body() -> Dict:
        return request.get_json(silent=True) or {}

    def input_path(job: Dict) -> str:
        return store.path(job["id"], "input.csv")

    def attempts_left(job: Dict) -> int:
        return max(0, settings.max_attempts - len(job["attempts"]))

    def void(job: Dict, reason: str) -> None:
        auth_id = job["paypal"].get("authorization_id")
        if auth_id:
            result = paypal.void_authorization(auth_id, request_id=f"{job['id']}-void")
            job["paypal"]["auth_status"] = result.get("status", "VOIDED")
            job["paypal"]["voided_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job["accept_nonce"] = None
        store.transition(job, VOIDED, f"PayPal authorization voided: {reason}")
        job["narration"] = narration.voided()

    def public(job: Dict) -> Dict:
        out = {k: v for k, v in job.items() if k not in ("attempts",)}
        if job["state"] != VERIFIED_PASS:
            out["accept_nonce"] = None
        out["attempts"] = [{k: v for k, v in a.items() if k != "changes"} for a in job["attempts"]]
        out["attempts_left"] = attempts_left(job)
        out["max_attempts"] = settings.max_attempts
        headers, rows = read_csv(input_path(job))
        out["input_preview"] = {"headers": headers, "rows": rows[:8]}
        if job["attempts"]:
            a = job["attempts"][-1]
            oh, orows = read_csv(store.path(job["id"], a["output_file"]))
            changed: Dict[str, Dict] = {}
            for c in a["changes"]:
                k = f"{c['row']}:{c['column']}"
                if k in changed:  # e.g. parsed to blank, then filled by a default: keep the original source value
                    changed[k]["note"] = f"{changed[k]['note']}; then {c['note']}"
                else:
                    changed[k] = {"before": c["before"], "note": c["note"]}
            failed = {}
            for c in a["report"]["checks"]:
                for f in c["failures"]:
                    for row in (f.get("rows") or [f.get("row")]):
                        if row and f.get("column"):
                            failed.setdefault(f"{row}:{f['column']}", {"reason": f["reason"], "severity": c["severity"]})
            out["preview"] = {"headers": oh, "rows": orows[:60], "changed": changed, "flagged": failed,
                              "total_rows": len(orows)}
        return out

    def respond(job: Dict, status: int = 200, **extra):
        payload = {"job": public(job), **extra}
        return jsonify(payload), status

    # --------------------------------------------------------------- errors
    @app.errorhandler(APIError)
    def _api_error(e: APIError):
        return jsonify({"error": str(e)}), e.status

    @app.errorhandler(StateError)
    def _state_error(e):
        return jsonify({"error": str(e)}), 409

    @app.errorhandler(CSVFormatError)
    def _csv_error(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(ContractError)
    @app.errorhandler(PlanError)
    def _contract_error(e):
        return jsonify({"error": f"The AI's proposal was rejected by validation: {e}"}), 422

    @app.errorhandler(LLMError)
    def _llm_error(e):
        return jsonify({"error": f"AI model problem: {e}"}), 502

    @app.errorhandler(PayPalError)
    def _paypal_error(e: PayPalError):
        return jsonify({"error": str(e), "paypal_debug_id": e.debug_id}), 502

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(e):
        return jsonify({"error": f"File too large. Limit is {settings.max_upload_mb} MB."}), 413

    # ---------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/config")
    def config():
        return {
            "paypal_mode": settings.paypal_mode,
            "paypal_client_id": settings.paypal_client_id if settings.paypal_mode == "sandbox" else None,
            "currency": settings.currency,
            "price": settings.job_price,
            "ai": llm.label,
            "ai_is_mock": llm.is_mock,
            "max_attempts": settings.max_attempts,
            "warnings": settings.warnings,
            "schema": load_schema(),
            "check_library": {t: {"label": m["label"], "severity": m["severity"]} for t, m in CHECK_LIBRARY.items()},
        }

    @app.get("/api/sample")
    def sample():
        return send_file(SAMPLE_PATH, mimetype="text/csv", as_attachment=True,
                         download_name="supplier_catalog_messy.csv")

    # ----------------------------------------------------------------- jobs
    @app.post("/api/jobs")
    def create_job():
        if request.form.get("sample") == "1":
            with open(SAMPLE_PATH, "rb") as f:
                raw = f.read()
            filename = os.path.basename(SAMPLE_PATH)
        else:
            upload = request.files.get("file")
            if not upload:
                raise APIError("Choose a CSV file to upload.")
            raw = upload.read()
            filename = secure_filename(upload.filename or "") or "upload.csv"
        headers, rows = parse_csv_text(decode_upload(raw), settings.max_rows)
        job = store.create(input_filename=filename, row_count=len(rows), headers=headers)
        with open(store.path(job["id"], "original_upload.csv"), "wb") as f:
            f.write(raw)
        write_csv(input_path(job), headers, rows)
        job["input_sha256"] = sha256_file(input_path(job))
        job["narration"] = (f"Got {filename}: {len(rows)} rows and {len(headers)} columns. "
                            "Now tell me what you need.")
        store.save(job)
        return respond(job, 201)

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id):
        return respond(load(job_id))

    @app.post("/api/jobs/<job_id>/contract")
    def propose_contract(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, UPLOADED, CONTRACT_PROPOSED, AGREED)
            text = str(body().get("request_text") or "").strip()
            if len(text) < 5:
                raise APIError("Tell VoxProof what you need first (speak or type).")
            headers, rows = read_csv(input_path(job))
            contract = draft_contract(llm=llm, job=job, request_text=text, headers=headers, sample_rows=rows,
                                      schema=schema, price=settings.job_price, currency=settings.currency)
            job["contract"] = contract
            job["contract_sha256"] = contract_hash(contract)
            job["paypal"] = {}
            with open(store.path(job_id, "contract.json"), "w", encoding="utf-8") as f:
                json.dump(contract, f, indent=1, ensure_ascii=False)
            store.transition(job, CONTRACT_PROPOSED,
                             f"Contract drafted by {contract['drafted_by']} ({len(contract['checks'])} checks), "
                             f"sha256 {job['contract_sha256'][:12]}")
            job["narration"] = narration.contract_ready(contract)
            store.save(job)
            return respond(job)

    @app.post("/api/jobs/<job_id>/agree")
    def agree(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, CONTRACT_PROPOSED)
            if body().get("contract_sha256") != job["contract_sha256"]:
                raise APIError("The contract changed since you viewed it. Please review it again.", 409)
            store.transition(job, AGREED, f"Customer tapped Agree on contract {job['contract_sha256'][:12]}")
            job["narration"] = narration.agreed(job["contract"])
            store.save(job)
            return respond(job)

    # --------------------------------------------------------------- PayPal
    @app.post("/api/jobs/<job_id>/paypal/order")
    def paypal_order(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, AGREED)
            price = job["contract"]["price"]
            order = paypal.create_order(amount=price["amount"], currency=price["currency"],
                                        custom_id=job["contract_sha256"], reference_id=job["id"],
                                        description=f"VoxProof verified catalog conversion {job['id'][:8]}")
            job["paypal"] = {"order_id": order["id"], "order_status": order.get("status")}
            store.note(job, f"PayPal order {order['id']} created (intent AUTHORIZE, custom_id = contract hash)")
            store.save(job)
            return jsonify({"id": order["id"]})

    @app.post("/api/jobs/<job_id>/paypal/authorize")
    def paypal_authorize(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, AGREED)
            order_id = body().get("order_id")
            if not order_id or order_id != job["paypal"].get("order_id"):
                raise APIError("Unknown PayPal order for this job.", 409)
            result = paypal.authorize_order(order_id, request_id=f"{job_id}-authorize")
            auth = first_authorization(result)
            job["paypal"].update({"authorization_id": auth["id"], "auth_status": auth.get("status"),
                                  "expiration_time": auth.get("expiration_time"),
                                  "authorized_amount": auth.get("amount"),
                                  "authorized_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            order = paypal.get_order(order_id)
            bound_hash = order["purchase_units"][0].get("custom_id")
            if bound_hash != job["contract_sha256"]:
                store.transition(job, AUTHORIZED, "Authorization received")
                void(job, "order was not bound to this contract")
                store.save(job)
                raise APIError("PayPal order doesn't match this contract. The hold was voided.", 409)
            if auth.get("status") not in ("CREATED",):
                store.save(job)
                raise APIError(f"PayPal authorization status is {auth.get('status')}; can't continue.", 409)
            store.transition(job, AUTHORIZED,
                             f"PayPal authorization {auth['id']} created: {auth.get('amount', {}).get('value')} "
                             f"{auth.get('amount', {}).get('currency_code')} on hold")
            job["narration"] = narration.authorized(job["contract"])
            store.save(job)
            return respond(job)

    # ----------------------------------------------------------- the work
    @app.post("/api/jobs/<job_id>/process")
    def process(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, AUTHORIZED, VERIFIED_FAIL)
            if attempts_left(job) <= 0:
                raise APIError("No attempts left.", 409)
            simulate_fault = bool(body().get("simulate_fault"))
            headers, rows = read_csv(input_path(job))
            feedback = None
            if job["attempts"] and not job["attempts"][-1]["report"]["passed"]:
                feedback = feedback_from_report(job["attempts"][-1]["report"])
            try:
                plan = plan_operations(llm=llm, contract=job["contract"], headers=headers, sample_rows=rows,
                                       schema=schema, feedback=feedback)
            except (PlanError, LLMError) as e:
                # The AI's plan was invalid or the model was unavailable. Fall back to a plan built
                # from the agreed mappings; it is still validated, executed and independently verified.
                app.logger.warning("AI worker plan unusable, using contract-derived plan: %s", e)
                fallback = heuristic_plan(job["contract"])
                plan = {"operations": validate_plan(fallback, headers, schema),
                        "notes": f"AI plan unusable ({str(e)[:120]}); used the plan derived from the agreed contract.",
                        "planned_by": "contract mappings (fallback)"}
            if simulate_fault:
                plan = inject_fault(plan, schema)

            n = len(job["attempts"]) + 1
            out_headers, out_rows, changes = execute(plan["operations"], headers, rows, schema)
            out_name = f"output_attempt{n}.csv"
            out_path = store.path(job_id, out_name)
            write_csv(out_path, out_headers, out_rows)
            report = verify_files(job["contract"], input_path(job), out_path, schema, job["contract_sha256"])

            job["attempts"].append({
                "n": n, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "plan": plan, "simulated_fault": simulate_fault, "output_file": out_name,
                "output_sha256": report["output_sha256"], "report": report, "changes": changes[:1000],
            })
            verdict = (f"{report['blocking_passed']}/{report['blocking_total']} required checks passed, "
                       f"{report['warning_count']} warnings")
            if report["passed"]:
                job["accept_nonce"] = secrets.token_urlsafe(18)
                store.transition(job, VERIFIED_PASS, f"Attempt {n} verified: PASS ({verdict})")
                job["narration"] = narration.verification(report, attempts_left(job), job["contract"])
            else:
                store.transition(job, VERIFIED_FAIL, f"Attempt {n} verified: FAIL ({verdict})"
                                 + (" [simulated faulty worker]" if simulate_fault else ""))
                job["narration"] = narration.verification(report, attempts_left(job), job["contract"])
                if attempts_left(job) == 0:
                    void(job, "no attempts left after failed verification")
                    job["narration"] = narration.verification(report, 0, job["contract"])
            store.save(job)
            return respond(job)

    @app.post("/api/jobs/<job_id>/ask")
    def ask(job_id):
        with job_lock(job_id):
            job = load(job_id)
            result = narration.answer_question(llm, job, str(body().get("text") or ""))
            if result["refused"]:
                store.note(job, f"Voice request to move money refused: \"{str(body().get('text'))[:80]}\"")
                store.save(job)
            return jsonify(result)

    # ------------------------------------------------------------ settle
    @app.post("/api/jobs/<job_id>/accept")
    def accept(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, VERIFIED_PASS)
            nonce = body().get("accept_nonce")
            if not nonce or not job.get("accept_nonce") or not secrets.compare_digest(nonce, job["accept_nonce"]):
                raise APIError("Accept must come from the Accept button on the review screen.", 403)
            attempt = job["attempts"][-1]
            out_path = store.path(job_id, attempt["output_file"])

            # Gate 1: re-run the independent verifier on the exact file being delivered.
            recheck = verify_files(job["contract"], input_path(job), out_path, schema, job["contract_sha256"])
            if not recheck["passed"] or recheck["output_sha256"] != attempt["output_sha256"]:
                raise APIError("Re-verification failed or the output changed. Not capturing.", 409)
            # Gate 2: the PayPal order must be bound to this exact contract.
            order = paypal.get_order(job["paypal"]["order_id"])
            if order["purchase_units"][0].get("custom_id") != job["contract_sha256"]:
                raise APIError("PayPal order isn't bound to this contract. Not capturing.", 409)
            # Gate 3: the authorization must still be valid.
            auth = paypal.get_authorization(job["paypal"]["authorization_id"])
            exp = auth.get("expiration_time")
            if auth.get("status") == "EXPIRED" or (exp and datetime.fromisoformat(exp.replace("Z", "+00:00")) < datetime.now(timezone.utc)):
                store.transition(job, EXPIRED, "Authorization expired before acceptance")
                job["narration"] = "The PayPal hold expired before you accepted, so nothing was charged."
                store.save(job)
                return respond(job)

            capture = paypal.capture_authorization(job["paypal"]["authorization_id"], request_id=f"{job_id}-capture")
            job["paypal"].update({"capture_id": capture.get("id"), "capture_status": capture.get("status"),
                                  "captured_amount": capture.get("amount"), "auth_status": "CAPTURED",
                                  "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            shutil.copyfile(out_path, store.path(job_id, "store_import.csv"))
            job["accept_nonce"] = None
            job["receipt"] = {
                "contract_sha256": job["contract_sha256"], "input_sha256": job["input_sha256"],
                "output_sha256": attempt["output_sha256"], "verified_at": recheck["verified_at"],
                "capture_id": capture.get("id"), "authorization_id": job["paypal"]["authorization_id"],
                "order_id": job["paypal"]["order_id"], "amount": job["contract"]["price"],
            }
            store.transition(job, CAPTURED, f"Customer tapped Accept. Re-verified and captured {capture.get('id')}")
            job["narration"] = narration.captured(job["contract"])
            store.save(job)
            return respond(job)

    @app.post("/api/jobs/<job_id>/reject")
    def reject(job_id):
        with job_lock(job_id):
            job = load(job_id)
            require(job, AUTHORIZED, VERIFIED_PASS, VERIFIED_FAIL)
            reason = str(body().get("reason") or "customer rejected the work")[:200]
            void(job, reason)
            store.save(job)
            return respond(job)

    # ---------------------------------------------------------- downloads
    @app.get("/api/jobs/<job_id>/output.csv")
    def output_csv(job_id):
        job = load(job_id)
        if job["state"] != CAPTURED:
            raise APIError("The file is delivered after payment is captured.", 403)
        return send_file(store.path(job_id, "store_import.csv"), mimetype="text/csv", as_attachment=True,
                         download_name="store_import.csv")

    @app.get("/api/jobs/<job_id>/evidence.json")
    def evidence(job_id):
        job = load(job_id)
        if job["state"] in (UPLOADED, CONTRACT_PROPOSED):
            raise APIError("No evidence yet.", 404)
        bundle = {
            "job_id": job["id"], "state": job["state"],
            "contract_sha256": job["contract_sha256"], "contract": job["contract"],
            "input_file": job["input_filename"], "input_sha256": job["input_sha256"],
            "paypal": job["paypal"], "receipt": job.get("receipt"),
            "attempts": [{"n": a["n"], "at": a["at"], "simulated_fault": a["simulated_fault"],
                          "plan": a["plan"], "report": a["report"]} for a in job["attempts"]],
            "events": job["events"],
        }
        resp = jsonify(bundle)
        resp.headers["Content-Disposition"] = f"attachment; filename=voxproof_evidence_{job_id[:8]}.json"
        return resp

    return app
