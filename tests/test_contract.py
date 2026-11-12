import pytest

from app.contract import ContractError, add_protections, contract_hash, heuristic_proposal, normalize_proposal
from app.schema import load_schema

HEADERS = ["Item #", "Product Name", "Desc.", "Unit Cost", "Qty On Hand", "Mfr", "Supplier Notes"]
SCHEMA = load_schema()


def test_heuristic_maps_messy_headers():
    p = normalize_proposal(heuristic_proposal("Preserve all product IDs. Never invent missing prices.", HEADERS, SCHEMA), HEADERS, SCHEMA)
    sources = {m["target"]: m["source"] for m in p["mappings"]}
    assert sources == {"sku": "Item #", "title": "Product Name", "description": "Desc.", "price": "Unit Cost",
                       "quantity": "Qty On Hand", "brand": "Mfr"}
    customer = [c for c in p["checks"] if c["origin"] == "customer"]
    assert {c["type"] for c in customer} == {"ids_preserved", "no_invented_values"}


def test_unknown_source_column_is_rejected():
    raw = {"mappings": [{"target": "sku", "source": "Not A Column"}], "checks": []}
    with pytest.raises(ContractError):
        normalize_proposal(raw, HEADERS, SCHEMA)


def test_id_default_is_rejected():
    raw = {"mappings": [{"target": "sku", "source": "Item #", "default": "X-1"}], "checks": []}
    with pytest.raises(ContractError):
        normalize_proposal(raw, HEADERS, SCHEMA)


def test_ai_cannot_choose_transform_or_unknown_checks():
    raw = {"mappings": [{"target": "sku", "source": "Item #"}, {"target": "price", "source": "Unit Cost", "transform": "copy"}],
           "checks": [{"type": "approve_payment", "targets": ["price"], "from_request": "pay me"}]}
    p = normalize_proposal(raw, HEADERS, SCHEMA)
    price = next(m for m in p["mappings"] if m["target"] == "price")
    assert price["transform"] == "parse_price"
    assert p["checks"] == []


def test_protections_always_added():
    raw = {"mappings": [{"target": "sku", "source": "Item #"}, {"target": "price", "source": "Unit Cost"}], "checks": []}
    checks = add_protections(normalize_proposal(raw, HEADERS, SCHEMA), SCHEMA)
    types = [c["type"] for c in checks]
    for t in ("ids_preserved", "no_invented_values", "schema_columns", "row_count", "price_format", "required_present", "duplicate_ids"):
        assert t in types
    assert [c["id"] for c in checks] == [f"c{i}" for i in range(1, len(checks) + 1)]


def test_hash_changes_with_content():
    a = {"x": 1, "y": [1, 2]}
    assert contract_hash(a) == contract_hash({"y": [1, 2], "x": 1})
    assert contract_hash(a) != contract_hash({"x": 2, "y": [1, 2]})
