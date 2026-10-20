import copy
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from naming import go_pascal  # noqa: E402

# oapi-codegen does not read OpenAPI 3.1 yet, and the spec leans on 3.1's
# `type: [x, "null"]` union everywhere. Downgrading a throwaway copy is cheaper
# than hand-writing a Go type emitter, and leaves the published spec untouched.


def convert(node):
    if isinstance(node, list):
        return [convert(item) for item in node]
    if not isinstance(node, dict):
        return node

    out = {key: convert(value) for key, value in node.items()}

    kind = out.get("type")
    if kind == "null":
        out.pop("type")
        out["nullable"] = True
        kind = None
    if isinstance(kind, list):
        concrete = [k for k in kind if k != "null"]
        if "null" in kind:
            out["nullable"] = True
        out["type"] = concrete[0] if len(concrete) == 1 else concrete
        if not concrete:
            out.pop("type")

    # 3.1 made exclusiveMinimum/Maximum numeric; 3.0 wants a bound plus a flag.
    for bound, flag in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
        value = out.get(flag)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[bound] = value
            out[flag] = True

    # A `{"type": "null"}` branch inside anyOf/oneOf has no 3.0 equivalent; it
    # becomes `nullable` on the parent and the branch goes away.
    for combinator in ("anyOf", "oneOf"):
        members = out.get(combinator)
        if not isinstance(members, list):
            continue
        kept = [m for m in members if not (isinstance(m, dict) and set(m) <= {"nullable"})]
        if len(kept) != len(members):
            out["nullable"] = True
        if len(kept) == 1 and isinstance(kept[0], dict):
            out.pop(combinator)
            merged = {**kept[0], **{k: v for k, v in out.items() if k != combinator}}
            out = merged
        else:
            out[combinator] = kept

    if "const" in out:
        out["enum"] = [out.pop("const")]
    out.pop("$schema", None)
    return out


def name_parameters(doc: dict) -> None:
    """Give every parameter an explicit Go name.

    oapi-codegen derives field names by stripping non-identifier characters, so
    `state` and `state!` both become `State` and the generated struct does not
    compile. `x-go-name` pins the names instead, keeping the wire name intact.
    """
    for methods in doc.get("paths", {}).values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters") or []:
                if re.fullmatch(r"[a-z][a-z0-9_]*", parameter["name"]):
                    continue
                field = go_pascal(parameter["name"])
                parameter["x-go-name"] = field
                # The enum type name is derived from the parameter name too, so
                # it collides in exactly the same way and needs pinning as well.
                schema = parameter.get("schema") or {}
                if schema.get("enum"):
                    schema["x-go-type-name"] = (
                        go_pascal(operation["operationId"].replace(".", "_")) + "Params" + field
                    )


def reachable(doc: dict, roots: set[str]) -> set[str]:
    schemas = doc.get("components", {}).get("schemas", {})
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        stack = [schemas[name]]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    queue.append(ref.rsplit("/", 1)[-1])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return seen


def strip_read_only(doc: dict) -> None:
    """Drop `readOnly` from schemas that only ever appear in responses.

    oapi-codegen turns a readOnly property into an optional pointer, so every
    response field the API always sends would arrive as *string. Request bodies
    keep their readOnly markers, where the flag genuinely means "do not send".
    """
    request_roots: set[str] = set()
    for methods in doc.get("paths", {}).values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            body = (operation.get("requestBody") or {}).get("content") or {}
            for media in body.values():
                ref = (media.get("schema") or {}).get("$ref")
                if isinstance(ref, str):
                    request_roots.add(ref.rsplit("/", 1)[-1])

    keep = reachable(doc, request_roots)
    for name, schema in doc.get("components", {}).get("schemas", {}).items():
        if name in keep:
            continue
        stack = [schema]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                node.pop("readOnly", None)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)


def build(spec_path: Path) -> dict:
    doc = convert(copy.deepcopy(yaml.safe_load(spec_path.read_text())))
    name_parameters(doc)
    strip_read_only(doc)
    doc["openapi"] = "3.0.3"
    # 3.0 has no top-level `webhooks`; the Go SDK carries the payload types by
    # hand, so dropping them here loses nothing the client needs.
    doc.pop("webhooks", None)
    return doc


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[2])
    out.write_text(yaml.safe_dump(build(Path(sys.argv[1])), sort_keys=False, width=10000))
    print(f"{out}: downgraded to 3.0.3")
