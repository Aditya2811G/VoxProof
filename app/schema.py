"""Target (store import) schema loading."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")

# Which transform each column type uses. The contract and the worker plan
# must agree with this table; the verifier re-derives expected values from it.
TRANSFORM_FOR_TYPE = {
    "id": "copy",
    "text": "copy",
    "price": "parse_price",
    "integer": "parse_integer",
}


@lru_cache(maxsize=8)
def load_schema(schema_id: str = "store_import") -> Dict:
    path = os.path.join(SCHEMA_DIR, f"{schema_id}.json")
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    ids = [c for c in schema["columns"] if c["type"] == "id"]
    if len(ids) != 1:
        raise ValueError("Schema must have exactly one id column")
    return schema


def column_names(schema: Dict) -> List[str]:
    return [c["name"] for c in schema["columns"]]


def column(schema: Dict, name: str) -> Dict:
    for c in schema["columns"]:
        if c["name"] == name:
            return c
    raise KeyError(name)


def id_column(schema: Dict) -> str:
    return next(c["name"] for c in schema["columns"] if c["type"] == "id")


def columns_of_type(schema: Dict, col_type: str) -> List[str]:
    return [c["name"] for c in schema["columns"] if c["type"] == col_type]


def required_columns(schema: Dict) -> List[str]:
    return [c["name"] for c in schema["columns"] if c.get("required")]
