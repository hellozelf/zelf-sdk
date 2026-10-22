import json
import re
from pathlib import Path

import pytest

MANIFEST = Path(__file__).resolve().parents[2] / "spec" / "names.json"
SDK = MANIFEST.parent.parent

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="names.json is written by `make all`")


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_every_operation_is_named_for_every_client():
    operations = manifest()["operations"]
    assert operations, "the manifest is empty"
    for operation_id, entry in operations.items():
        missing = {
            "python",
            "typescript",
            "go",
            "rust",
            "ruby",
            "csharp",
            "java",
        } - set(entry["symbols"])
        assert not missing, f"{operation_id} is missing {sorted(missing)}"


def test_the_python_symbols_are_the_ones_the_client_exposes():
    """The manifest is what the docs render, so a wrong name is a wrong doc."""
    for operation_id, entry in manifest()["operations"].items():
        symbols = entry["symbols"]["python"]
        module = SDK / "python" / "zelf" / "resources" / f"{symbols['resource']}.py"
        assert module.exists(), f"{operation_id}: no resource module {module.name}"
        assert re.search(rf"^    def {re.escape(symbols['method'])}\(", module.read_text(), re.M), (
            f"{operation_id}: {symbols['resource']}.{symbols['method']} is not defined"
        )


def test_the_typescript_and_go_symbols_are_the_ones_those_clients_expose():
    for operation_id, entry in manifest()["operations"].items():
        ts = entry["symbols"]["typescript"]
        module = SDK / "js" / "src" / "resources" / f"{ts['resource']}.ts"
        assert module.exists(), f"{operation_id}: no js resource {module.name}"
        assert re.search(rf"^  (?:async )?{re.escape(ts['method'])}\(", module.read_text(), re.M), (
            f"{operation_id}: js {ts['resource']}.{ts['method']} is not defined"
        )

        go = entry["symbols"]["go"]
        source = SDK / "go" / f"resource_{entry['symbols']['python']['resource']}.go"
        assert source.exists(), f"{operation_id}: no go source {source.name}"
        assert re.search(
            rf"func \(r \*\w+Resource\) {re.escape(go['method'])}\(",
            source.read_text(),
        ), f"{operation_id}: go {go['resource']}.{go['method']} is not defined"


def test_the_cardinality_matches_the_python_return_type():
    """A list operation returns a list, which is what a snippet has to show."""
    for operation_id, entry in manifest()["operations"].items():
        symbols = entry["symbols"]["python"]
        module = SDK / "python" / "zelf" / "resources" / f"{symbols['resource']}.py"
        signature = re.search(
            rf"^    def {re.escape(symbols['method'])}\((?:.|\n)*?-> (.+):$",
            module.read_text(),
            re.M,
        )
        assert signature, f"{operation_id}: no return type found"
        returned = signature.group(1)
        if entry["cardinality"] == "list":
            assert returned.startswith("list["), f"{operation_id} -> {returned}"
        elif entry["cardinality"] == "page":
            assert "Page" in returned, f"{operation_id} -> {returned}"
