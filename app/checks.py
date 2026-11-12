"""The acceptance-check library.

The AI may only *choose* checks from this library and say which columns they
apply to. Every check here is implemented in plain code in verifier.py.
Severity is fixed here: the AI cannot downgrade a blocking check.
"""
from __future__ import annotations

from typing import Dict, List

BLOCKING = "blocking"
WARNING = "warning"

CHECK_LIBRARY: Dict[str, Dict] = {
    "schema_columns": {
        "spoken": "Column layout",
        "severity": BLOCKING,
        "label": "Output has exactly the store's columns, in order",
        "description": "The output header must equal the target schema columns.",
        "takes_targets": False,
    },
    "row_count": {
        "spoken": "Row count",
        "severity": BLOCKING,
        "label": "Same number of rows in and out",
        "description": "No rows may be dropped or added.",
        "takes_targets": False,
    },
    "ids_preserved": {
        "spoken": "Product IDs",
        "severity": BLOCKING,
        "label": "Product IDs copied exactly ({targets})",
        "description": "Each output ID must equal the source ID on the same row (surrounding spaces trimmed). No IDs changed, added or removed.",
        "takes_targets": True,
    },
    "no_invented_values": {
        "spoken": "No invented values in {targets}",
        "severity": BLOCKING,
        "label": "Nothing invented in {targets}: every value traces back to your file",
        "description": "Each non-blank output value must be derivable from the source cell on the same row. If the source is blank or unclear, the output must stay blank (or use a default the customer explicitly agreed to).",
        "takes_targets": True,
    },
    "price_format": {
        "spoken": "Price format",
        "severity": BLOCKING,
        "label": "Prices are positive numbers with 2 decimals ({targets})",
        "description": "Non-blank values must look like 12.50 and be greater than zero.",
        "takes_targets": True,
    },
    "integer_format": {
        "spoken": "Quantity format",
        "severity": BLOCKING,
        "label": "Quantities are whole numbers ({targets})",
        "description": "Non-blank values must be whole numbers of zero or more.",
        "takes_targets": True,
    },
    "required_present": {
        "spoken": "Missing required fields",
        "severity": WARNING,
        "label": "Missing required fields are flagged for you ({targets})",
        "description": "Lists rows where a required column is blank because the source had no usable value. These rows are shown for review, never filled in.",
        "takes_targets": True,
    },
    "duplicate_ids": {
        "spoken": "Duplicate IDs",
        "severity": WARNING,
        "label": "Duplicate product IDs are flagged for you ({targets})",
        "description": "Lists IDs that appear on more than one row, so you can decide which one is correct.",
        "takes_targets": True,
    },
}

# Checks the AI is asked to choose from (the rest are always added).
REQUESTABLE = ["ids_preserved", "no_invented_values", "price_format", "integer_format", "required_present", "duplicate_ids"]


def check_label(check: Dict) -> str:
    meta = CHECK_LIBRARY[check["type"]]
    targets = ", ".join(check.get("targets") or [])
    return meta["label"].format(targets=targets or "all columns")


def spoken_label(check: Dict) -> str:
    meta = CHECK_LIBRARY[check["type"]]
    return meta["spoken"].format(targets=" and ".join(check.get("targets") or []))


def check_severity(check_type: str) -> str:
    return CHECK_LIBRARY[check_type]["severity"]


def library_for_prompt() -> List[Dict]:
    return [
        {"type": t, "severity": CHECK_LIBRARY[t]["severity"], "what_it_checks": CHECK_LIBRARY[t]["description"]}
        for t in REQUESTABLE
    ]
