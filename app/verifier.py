"""Independent verifier.

Reads the input and output files from disk and checks the output against the
agreed contract. It has no access to the AI, the worker plan, the executor or
the payment client, and it never imports them (a test enforces this).
Its value parsers are written separately from the executor's on purpose.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from .checks import BLOCKING, CHECK_LIBRARY, check_label, spoken_label
from .csvio import read_csv, sha256_file
from .schema import column_names

MAX_DETAILS = 25
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def expected_price(raw: str) -> Optional[Decimal]:
    text = (raw or "").strip()
    if text == "":
        return None
    matches = list(_NUMBER.finditer(text))
    if len(matches) != 1:
        return None
    m = matches[0]
    before = text[:m.start()].rstrip()
    if before.endswith("-"):
        return None
    token = m.group(0)
    groups = re.split(r"[.,]", token)
    seps = re.findall(r"[.,]", token)
    if not seps:
        value = Decimal(groups[0])
    elif len(groups[-1]) in (1, 2):
        decimal_sep = seps[-1]
        if decimal_sep in seps[:-1]:
            return None
        value = Decimal("".join(groups[:-1]) + "." + groups[-1])
    elif len(groups[-1]) == 3:
        if all(s == "," for s in seps):
            value = Decimal("".join(groups))
        elif all(s == "." for s in seps) and len(seps) > 1:
            value = Decimal("".join(groups))
        else:
            return None
    else:
        return None
    if value <= 0:
        return None
    return value


def expected_integer(raw: str) -> Optional[int]:
    text = (raw or "").strip()
    if text == "":
        return None
    parts = text.split(",")
    if len(parts) > 1:
        if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
            return None
        text = "".join(parts)
    if not (text.isascii() and text.isdigit()):
        return None
    return int(text)


def _expected_value(transform: str, raw: str) -> Optional[str]:
    """What the output cell should contain for this source cell (None = blank)."""
    if transform == "copy":
        v = (raw or "").strip()
        return v or None
    if transform == "parse_price":
        p = expected_price(raw)
        return None if p is None else f"{p:.2f}"
    if transform == "parse_integer":
        n = expected_integer(raw)
        return None if n is None else str(n)
    return None


def _same(transform: str, a: str, b: str) -> bool:
    if transform == "parse_price":
        try:
            return Decimal(a) == Decimal(b)
        except Exception:
            return False
    return a == b


def verify_files(contract: Dict, input_path: str, output_path: str, schema: Dict,
                 contract_sha256: Optional[str] = None) -> Dict:
    in_headers, in_rows = read_csv(input_path)
    out_headers, out_rows = read_csv(output_path)
    src_index = {h: i for i, h in enumerate(in_headers)}
    out_index = {h: i for i, h in enumerate(out_headers)}
    mappings = {m["target"]: m for m in contract["mappings"]}

    def out_cell(r: int, col: str) -> str:
        row = out_rows[r]
        i = out_index.get(col)
        return row[i] if i is not None and i < len(row) else ""

    def src_cell(r: int, col: Optional[str]) -> str:
        if col is None or col not in src_index or r >= len(in_rows):
            return ""
        return in_rows[r][src_index[col]]

    rows_comparable = len(in_rows) == len(out_rows)
    results = []

    for check in contract["checks"]:
        ctype = check["type"]
        targets = check.get("targets") or []
        failures: List[Dict] = []
        note = ""

        if ctype == "schema_columns":
            expected = column_names(schema)
            if out_headers != expected:
                failures.append({"row": None, "column": None, "value": ", ".join(out_headers),
                                 "reason": f"expected columns: {', '.join(expected)}"})

        elif ctype == "row_count":
            if not rows_comparable:
                failures.append({"row": None, "column": None, "value": str(len(out_rows)),
                                 "reason": f"input has {len(in_rows)} rows, output has {len(out_rows)}"})

        elif ctype in ("ids_preserved", "no_invented_values"):
            if not rows_comparable:
                note = "Skipped: row counts differ, so rows can't be matched."
                failures.append({"row": None, "column": None, "value": "", "reason": note})
            else:
                for col in targets:
                    m = mappings.get(col, {"source": None, "transform": "copy", "default": None})
                    for r in range(len(out_rows)):
                        got = out_cell(r, col)
                        raw = src_cell(r, m.get("source"))
                        if ctype == "ids_preserved":
                            want = raw.strip()
                            if got != want:
                                failures.append({"row": r + 1, "column": col, "value": got,
                                                 "reason": f"ID changed: source says '{want}'"})
                            continue
                        want = _expected_value(m.get("transform", "copy"), raw) if m.get("source") else None
                        if want is not None:
                            if not _same(m.get("transform", "copy"), got, want):
                                failures.append({"row": r + 1, "column": col, "value": got,
                                                 "reason": f"doesn't match the source value '{raw.strip()}' (expected '{want}')"})
                        elif got != "":
                            default = m.get("default")
                            if default is None or got != default:
                                src_desc = f"'{raw.strip()}'" if raw.strip() else "blank"
                                failures.append({"row": r + 1, "column": col, "value": got,
                                                 "reason": f"not in your file (source was {src_desc}) and no default was agreed"})

        elif ctype == "price_format":
            for col in targets:
                for r in range(len(out_rows)):
                    v = out_cell(r, col)
                    if v and (not re.fullmatch(r"\d+\.\d{2}", v) or Decimal(v) <= 0):
                        failures.append({"row": r + 1, "column": col, "value": v, "reason": "not a price like 12.50"})

        elif ctype == "integer_format":
            for col in targets:
                for r in range(len(out_rows)):
                    v = out_cell(r, col)
                    if v and not re.fullmatch(r"\d+", v):
                        failures.append({"row": r + 1, "column": col, "value": v, "reason": "not a whole number"})

        elif ctype == "required_present":
            for col in targets:
                for r in range(len(out_rows)):
                    if out_cell(r, col) == "":
                        m = mappings.get(col, {})
                        raw = src_cell(r, m.get("source")).strip()
                        why = f"source was '{raw}'" if raw else "source was blank"
                        failures.append({"row": r + 1, "column": col, "value": "",
                                         "reason": f"left blank, {why}. Please fill it in yourself."})

        elif ctype == "duplicate_ids":
            for col in targets:
                seen = defaultdict(list)
                for r in range(len(out_rows)):
                    v = out_cell(r, col)
                    if v:
                        seen[v].append(r + 1)
                for value, rows in seen.items():
                    if len(rows) > 1:
                        failures.append({"row": rows[0], "rows": rows, "column": col, "value": value,
                                         "reason": f"appears on rows {', '.join(map(str, rows))}"})

        severity = CHECK_LIBRARY[ctype]["severity"]
        results.append({
            "id": check["id"],
            "type": ctype,
            "targets": targets,
            "label": check_label(check),
            "spoken": spoken_label(check),
            "severity": severity,
            "origin": check.get("origin"),
            "from_request": check.get("from_request"),
            "passed": not failures,
            "failure_count": len(failures),
            "failures": failures[:MAX_DETAILS],
            "note": note,
        })

    blocking = [c for c in results if c["severity"] == BLOCKING]
    warnings = [c for c in results if c["severity"] != BLOCKING and not c["passed"]]
    attention_rows = sorted({r for c in warnings for f in c["failures"] for r in (f.get("rows") or [f["row"]]) if r})
    return {
        "passed": all(c["passed"] for c in blocking),
        "blocking_total": len(blocking),
        "blocking_passed": sum(1 for c in blocking if c["passed"]),
        "warning_count": len(warnings),
        "attention_rows": attention_rows,
        "checks": results,
        "input_sha256": sha256_file(input_path),
        "output_sha256": sha256_file(output_path),
        "contract_sha256": contract_sha256,
        "rows_in": len(in_rows),
        "rows_out": len(out_rows),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "verifier": "voxproof-verifier/1 (plain Python, no AI)",
    }
