import ast
import os

import pytest

from app.executor import parse_integer, parse_price
from app.verifier import expected_integer, expected_price

PRICE_CASES = {
    "$24.99": "24.99", "12,50": "12.50", "USD 18": "18.00", "1,299.00": "1299.00", "14,00 €": "14.00",
    "1.249,00": "1249.00", "7.5": "7.50", "€ 22": "22.00", "1,299": "1299.00", "1.234.567,89": "1234567.89",
    "N/A": None, "": None, "call for price": None, "12.499": None, "-5": None, "0": None,
    "1 299,00": None, "12.50 / 10.00": None,
}


@pytest.mark.parametrize("raw,want", PRICE_CASES.items())
def test_price_rules(raw, want):
    got, _ = parse_price(raw)
    assert got == want
    independent = expected_price(raw)
    assert (None if independent is None else f"{independent:.2f}") == want


@pytest.mark.parametrize("raw,want", {"120": "120", "1,200": "1200", "approx 50": None, "12.0": None, "-3": None, "": None}.items())
def test_integer_rules(raw, want):
    got, _ = parse_integer(raw)
    assert got == want
    independent = expected_integer(raw)
    assert (None if independent is None else str(independent)) == want


def test_verifier_is_independent():
    """The verifier must not import the AI, the worker, the executor or PayPal."""
    path = os.path.join(os.path.dirname(__file__), "..", "app", "verifier.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for banned in ("executor", "llm", "worker", "paypal", "narration", "main", "requests"):
        assert not any(banned in m for m in imported), f"verifier imports {banned}"
