import hashlib
import json
import re

import models as model_ir
from spec import Api, Param, Type

# Prose moves on every docs edit and changes nothing a caller can call, so it
# is left out. What stays is the surface a client is generated from: if any of
# it moves, some client's public API moves with it.


def type_shape(node: Type) -> dict:
    out: dict = {"kind": node.kind}
    if node.enum:
        out["enum"] = sorted(str(v) for v in node.enum)
    if node.ref:
        out["ref"] = node.ref
    if node.min_items:
        out["min_items"] = node.min_items
    if node.item is not None:
        out["item"] = type_shape(node.item)
    return out


def param_shape(param: Param) -> dict:
    return {
        "name": param.name,
        "in": param.location,
        "required": param.required,
        "type": type_shape(param.type),
    }


def shape(api: Api) -> dict:
    """The structural surface of the document, with every description gone."""
    models, enums = model_ir.build(api)
    return {
        "operations": sorted(
            (
                {
                    "id": op.operation_id,
                    "http_method": op.http_method,
                    "path": op.path,
                    "status": op.status,
                    "cardinality": op.cardinality,
                    "item": op.item,
                    "body": op.body,
                    "body_required": op.body_required,
                    "path_params": [param_shape(p) for p in op.path_params],
                    "query_params": sorted(
                        (param_shape(p) for p in op.query_params),
                        key=lambda p: p["name"],
                    ),
                    "body_fields": sorted(
                        (param_shape(p) for p in op.body_fields),
                        key=lambda p: p["name"],
                    ),
                }
                for op in api.operations
            ),
            key=lambda o: o["id"],
        ),
        "models": sorted(
            (
                {
                    "name": m.name,
                    "fields": sorted(
                        (
                            {
                                "name": f.name,
                                "required": f.required,
                                "nullable": f.nullable,
                                "read_only": f.read_only,
                                "type": type_shape(f.type),
                            }
                            for f in m.fields
                        ),
                        key=lambda f: f["name"],
                    ),
                }
                for m in models
            ),
            key=lambda m: m["name"],
        ),
        "enums": sorted(
            ({"name": e.name, "values": sorted(e.values)} for e in enums),
            key=lambda e: e["name"],
        ),
        "webhooks": sorted(
            (
                {"name": w.name, "event_type": w.event_type, "payload": w.payload}
                for w in api.webhooks
            ),
            key=lambda w: w["name"],
        ),
        "error_codes": {
            str(status): sorted(codes)
            for status, codes in sorted(api.error_codes.items())
        },
    }


def canonical(api: Api) -> str:
    return json.dumps(shape(api), sort_keys=True, separators=(",", ":"))


def fingerprint(api: Api) -> str:
    return hashlib.sha256(canonical(api).encode()).hexdigest()


PATH_VERSION = re.compile(r"^/api/(v\d+)/")


def path_versions(state: dict) -> set[str]:
    """The URL versions the document serves, for example {"v1"}.

    The API carries its compatibility boundary in the path, so this, rather
    than a removal, is what makes a change breaking.
    """
    found = set()
    for operation in state["operations"]:
        match = PATH_VERSION.match(operation["path"])
        if match:
            found.add(match.group(1))
    return found
