"""File-based job store and the job state machine."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

UPLOADED = "UPLOADED"
CONTRACT_PROPOSED = "CONTRACT_PROPOSED"
AGREED = "AGREED"
AUTHORIZED = "AUTHORIZED"
VERIFIED_FAIL = "VERIFIED_FAIL"
VERIFIED_PASS = "VERIFIED_PASS"
CAPTURED = "CAPTURED"
VOIDED = "VOIDED"
EXPIRED = "EXPIRED"

TRANSITIONS = {
    UPLOADED: {CONTRACT_PROPOSED},
    CONTRACT_PROPOSED: {CONTRACT_PROPOSED, AGREED},
    AGREED: {AUTHORIZED, CONTRACT_PROPOSED},
    AUTHORIZED: {VERIFIED_PASS, VERIFIED_FAIL, VOIDED, EXPIRED},
    VERIFIED_FAIL: {VERIFIED_PASS, VERIFIED_FAIL, VOIDED, EXPIRED},
    VERIFIED_PASS: {CAPTURED, VOIDED, EXPIRED},
    CAPTURED: set(),
    VOIDED: set(),
    EXPIRED: set(),
}
TERMINAL = {CAPTURED, VOIDED, EXPIRED}

_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class StateError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, data_dir: str):
        self.root = os.path.join(data_dir, "jobs")
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def dir(self, job_id: str) -> str:
        if not _ID_RE.match(job_id or ""):
            raise KeyError(job_id)
        return os.path.join(self.root, job_id)

    def path(self, job_id: str, name: str) -> str:
        return os.path.join(self.dir(job_id), name)

    def create(self, **fields) -> Dict:
        job_id = uuid.uuid4().hex
        os.makedirs(self.dir(job_id), exist_ok=True)
        job = {"id": job_id, "state": UPLOADED, "created_at": now(), "updated_at": now(),
               "contract": None, "contract_sha256": None, "paypal": {}, "attempts": [],
               "events": [], "narration": "", **fields}
        self._event(job, UPLOADED, f"Uploaded {fields.get('input_filename', 'file')} ({fields.get('row_count', 0)} rows)")
        self.save(job)
        return job

    def get(self, job_id: str) -> Optional[Dict]:
        try:
            p = self.path(job_id, "job.json")
        except KeyError:
            return None
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def save(self, job: Dict) -> None:
        with self._lock:
            job["updated_at"] = now()
            p = self.path(job["id"], "job.json")
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(job, f, indent=1, ensure_ascii=False)
            os.replace(tmp, p)

    @staticmethod
    def _event(job: Dict, state: str, message: str) -> None:
        job["events"].append({"at": now(), "state": state, "message": message})

    def transition(self, job: Dict, new_state: str, message: str) -> None:
        if new_state not in TRANSITIONS[job["state"]]:
            raise StateError(f"Can't go from {job['state']} to {new_state}.")
        job["state"] = new_state
        self._event(job, new_state, message)

    def note(self, job: Dict, message: str) -> None:
        self._event(job, job["state"], message)

    def lock(self):
        return self._lock
