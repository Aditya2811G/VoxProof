"""Executes an AI-proposed operation plan.

The AI never touches the data. It proposes a list of operations from the
fixed library below; this module validates the plan and runs it with plain
code. The executor does not judge the result - verifier.py does that,
independently, from the files on disk.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from .schema import column_names

OPERATIONS = {
    "copy": "Copy the source cell, trimming surrounding spaces.",
    "parse_price": "Read a price written in any common format (e.g. $1,299.00, 12,50 EUR, USD 18) and write it as 1299.00. Unclear or missing prices are left blank.",
    "parse_integer": "Read a whole number (e.g. 1,200 -> 1200). Anything unclear is left blank.",
    "fill_default": "Fill blank cells in the target column with a fixed value. Runs after the other operations.",
}
PRIMARY_OPS = {"copy", "parse_price", "parse_integer"}


class PlanError(ValueError):
    pass


# --------------------------------------------------------------------------
# Value parsers (executor side). verifier.py has its own, separately written
# implementation of the same rules so that one bug can't hide in both.
# --------------------------------------------------------------------------
_NUMBER_RUN = re.compile(r"\d[\d.,]*")


def parse_price(raw: str) -> Tuple[Optional[str], str]:
    """Return (normalised price or None, note)."""
    s = (raw or "").strip()
    if not s:
        return None, "blank in source"
    if re.search(r"-\s*\d", s):
        return None, "negative or range, left blank"
    runs = _NUMBER_RUN.findall(s)
    if not runs:
        return None, "no price in source, left blank"
    if len(runs) > 1:
        return None, "more than one number, left blank"
    num = runs[0].rstrip(".,")
    separators = [(i, ch) for i, ch in enumerate(num) if ch in ".,"]
    try:
        if not separators:
            value = Decimal(num)
        else:
            last_i, last_ch = separators[-1]
            tail = num[last_i + 1:]
            head = num[:last_i]
            if 1 <= len(tail) <= 2:
                if last_ch in head:
                    return None, "unclear number format, left blank"
                value = Decimal(head.replace(".", "").replace(",", "") + "." + tail)
            elif len(tail) == 3:
                if last_ch == "," and "." not in num:
                    value = Decimal(num.replace(",", ""))
                elif last_ch == "." and num.count(".") > 1 and "," not in num:
                    value = Decimal(num.replace(".", ""))
                else:
                    return None, "ambiguous decimals, left blank"
            else:
                return None, "unclear number format, left blank"
    except InvalidOperation:
        return None, "unclear number format, left blank"
    if value <= 0:
        return None, "zero or negative, left blank"
    return str(value.quantize(Decimal("0.01"))), "parsed price"


def parse_integer(raw: str) -> Tuple[Optional[str], str]:
    s = (raw or "").strip()
    if not s:
        return None, "blank in source"
    if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        s = s.replace(",", "")
    if re.fullmatch(r"\d+", s):
        return str(int(s)), "parsed number"
    return None, "not a clear whole number, left blank"


# --------------------------------------------------------------------------
# Plan validation and execution
# --------------------------------------------------------------------------
def validate_plan(plan: Dict, source_headers: List[str], schema: Dict) -> List[Dict]:
    if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list):
        raise PlanError("Plan must be an object with an 'operations' list.")
    targets = set(column_names(schema))
    seen_primary = set()
    clean: List[Dict] = []
    for i, op in enumerate(plan["operations"]):
        if not isinstance(op, dict):
            raise PlanError(f"Operation {i + 1} is not an object.")
        kind = op.get("op")
        target = op.get("target")
        if kind not in OPERATIONS:
            raise PlanError(f"Operation {i + 1}: '{kind}' is not an allowed operation.")
        if target not in targets:
            raise PlanError(f"Operation {i + 1}: target '{target}' is not a store column.")
        item = {"op": kind, "target": target}
        if kind in PRIMARY_OPS:
            source = op.get("source")
            if source not in source_headers:
                raise PlanError(f"Operation {i + 1}: source column '{source}' is not in the uploaded file.")
            if target in seen_primary:
                raise PlanError(f"Operation {i + 1}: '{target}' is filled twice.")
            seen_primary.add(target)
            item["source"] = source
        else:
            value = op.get("value")
            if not isinstance(value, (str, int, float)) or str(value).strip() == "":
                raise PlanError(f"Operation {i + 1}: fill_default needs a non-empty value.")
            item["value"] = str(value).strip()[:200]
        if op.get("injected_fault"):
            item["injected_fault"] = True
        clean.append(item)
    if not clean:
        raise PlanError("Plan has no operations.")
    return clean


def execute(ops: List[Dict], source_headers: List[str], source_rows: List[List[str]], schema: Dict):
    """Run validated ops. Returns (output_headers, output_rows, changes)."""
    out_headers = column_names(schema)
    src_index = {h: i for i, h in enumerate(source_headers)}
    out_index = {h: i for i, h in enumerate(out_headers)}
    out_rows = [[""] * len(out_headers) for _ in source_rows]
    changes: List[Dict] = []

    primary = [o for o in ops if o["op"] in PRIMARY_OPS]
    defaults = [o for o in ops if o["op"] == "fill_default"]

    for r, row in enumerate(source_rows):
        for op in primary:
            raw = row[src_index[op["source"]]]
            if op["op"] == "copy":
                value, note = raw.strip(), ("trimmed spaces" if raw != raw.strip() else "")
            elif op["op"] == "parse_price":
                value, note = parse_price(raw)
            else:
                value, note = parse_integer(raw)
            out_rows[r][out_index[op["target"]]] = value or ""
            if (value or "") != raw:
                changes.append({"row": r + 1, "column": op["target"], "source_column": op["source"],
                                "before": raw, "after": value or "", "note": note})
        for op in defaults:
            c = out_index[op["target"]]
            if out_rows[r][c] == "":
                out_rows[r][c] = op["value"]
                changes.append({"row": r + 1, "column": op["target"], "source_column": None,
                                "before": "", "after": op["value"],
                                "note": "filled default" + (" (injected fault)" if op.get("injected_fault") else "")})
    return out_headers, out_rows, changes
