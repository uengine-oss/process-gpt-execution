import json
from pathlib import Path

import pytest
from process_definition import load_process_definition


TEST_JSON_PATH = Path(__file__).resolve().parent / "test.json"


@pytest.fixture(scope="module")
def parent_def():
    assert TEST_JSON_PATH.exists(), f"Test data JSON not found: {TEST_JSON_PATH}"
    with TEST_JSON_PATH.open("r", encoding="utf-8") as f:
        parent_def_dict = json.load(f)
    return load_process_definition(parent_def_dict)


def test_loads_process_definition(parent_def):
    # Sanity check: object returned
    assert parent_def is not None


def test_find_known_gateway_block(parent_def):
    target_id = "Gateway_0do2146"
    gateway = parent_def.find_gateway_by_id(target_id)
    assert gateway is not None, f"Gateway not found: {target_id}"
    assert getattr(gateway, "id", None) == target_id

