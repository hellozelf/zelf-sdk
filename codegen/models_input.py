import json
import re
from pathlib import Path

import yaml

# `PaginatedXList` is a bare `array of X` alias used only inside the response
# envelope; the SDK's Page[T] carries the element type, so the aliases would
# generate 19 RootModel classes nobody calls.
SKIP = re.compile(r"^Paginated.*List$")

PRIMITIVES = {"string", "integer", "number", "boolean"}
ITEM_NOISE = ("minLength", "maxLength", "pattern", "description", "title")
# `format: uri` makes pydantic emit AnyUrl, which does not round-trip through
# json() as the plain string the API sent. date-time is kept.
DROPPED_FORMATS = {"uri", "uri-reference", "url", "slug", "hostname"}


def primitive(node: dict) -> bool:
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if isinstance(k, str) and k != "null"), None)
    return isinstance(kind, str) and kind in PRIMITIVES and "enum" not in node


def normalise(node, inside_items=False):
    if isinstance(node, list):
        return [normalise(child) for child in node]
    if not isinstance(node, dict):
        return node

    out = {k: normalise(v, inside_items=(k == "items")) for k, v in node.items()}
    if primitive(out):
        if out.get("format") in DROPPED_FORMATS:
            out.pop("format")
        # Element-level constraints are server-enforced; carrying them makes
        # datamodel-codegen wrap every constrained string in its own RootModel.
        if inside_items:
            for key in ITEM_NOISE:
                out.pop(key, None)
    return out


def build(spec_path: Path) -> dict:
    doc = yaml.safe_load(spec_path.read_text())
    schemas = {k: v for k, v in doc["components"]["schemas"].items() if not SKIP.match(k)}
    text = json.dumps(normalise(schemas)).replace("#/components/schemas/", "#/$defs/")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": json.loads(text)}


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[2])
    out.write_text(json.dumps(build(Path(sys.argv[1])), indent=1))
    print(f"{out}: {len(json.loads(out.read_text())['$defs'])} schemas")
