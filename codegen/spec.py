import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from naming import FORCE_LIST, FORCE_SINGLE, OPERATION_RENAMES, snake

ENVELOPE_KEYS = {
    "log_id", "timestamp", "applied_filters", "results",
    "item_count", "page", "next", "previous",
}


@dataclass
class Type:
    kind: str  # str | int | float | bool | datetime | array | enum | ref | any
    enum: list[str] | None = None
    item: "Type | None" = None
    ref: str | None = None
    min_items: int = 0


@dataclass
class Param:
    name: str
    location: str  # path | query
    required: bool
    type: Type
    description: str = ""


@dataclass
class Operation:
    operation_id: str
    raw_operation_id: str
    resource: str
    method: str
    http_method: str
    path: str
    path_params: list[Param] = field(default_factory=list)
    query_params: list[Param] = field(default_factory=list)
    body: str | None = None
    body_required: bool = False
    body_fields: list[Param] = field(default_factory=list)
    status: int = 200
    item: str | None = None
    cardinality: str = "single"  # single | list | page
    summary: str = ""
    description: str = ""

    @property
    def returns_nothing(self) -> bool:
        return self.item is None


@dataclass
class Webhook:
    name: str
    event_type: str
    payload: str
    description: str


@dataclass
class Api:
    title: str
    version: str
    server: str
    description: str
    operations: list[Operation]
    schemas: dict
    webhooks: list[Webhook]
    error_codes: dict[int, list[str]]

    @property
    def resources(self) -> dict[str, list[Operation]]:
        out: dict[str, list[Operation]] = {}
        for op in self.operations:
            out.setdefault(op.resource, []).append(op)
        return out


NULL_SCHEMA_REFS = ("NullEnum", "BlankEnum")


def is_null_schema(member: dict) -> bool:
    """Whether a `oneOf` member only exists to mark the field nullable."""
    if member.get("type") == "null":
        return True
    ref = member.get("$ref", "").rsplit("/", 1)[-1]
    return ref in NULL_SCHEMA_REFS


def resolve_type(schema: dict) -> Type:
    if not schema:
        return Type("any")
    # drf-spectacular wraps a $ref in `allOf` whenever it also attaches a
    # description or default, so unwrap the single-member case.
    members = schema.get("allOf")
    if isinstance(members, list) and len(members) == 1:
        merged = {k: v for k, v in schema.items() if k != "allOf"}
        return resolve_type({**members[0], **{k: v for k, v in merged.items() if k != "description"}})
    if "$ref" in schema:
        return Type("ref", ref=schema["$ref"].rsplit("/", 1)[-1])
    # drf-spectacular spells a nullable field as a `oneOf` of the real schema
    # and a null one, so drop the null member and keep the type it wraps.
    variants = schema.get("oneOf")
    if isinstance(variants, list):
        real = [m for m in variants if not is_null_schema(m)]
        if len(real) == 1:
            merged = {k: v for k, v in schema.items() if k not in ("oneOf", "description")}
            return resolve_type({**real[0], **merged})
    raw = schema.get("type")
    if isinstance(raw, list):
        raw = next((t for t in raw if t != "null"), "string")
    if "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        # A named enum becomes an identifier per member in every language, and
        # only strings make identifiers. A numeric enum stays its scalar type
        # and is left to the API to enforce.
        if values and all(isinstance(v, str) for v in values):
            return Type("enum", enum=list(schema["enum"]))
        # A numeric enum keeps its scalar type, but the allowed values ride
        # along so a generated sample picks one the API will accept.
        if values:
            kind = "float" if any(isinstance(v, float) for v in values) else "int"
            return Type(kind, enum=values)
    if raw == "array":
        return Type(
            "array",
            item=resolve_type(schema.get("items", {})),
            min_items=int(schema.get("minItems") or 0),
        )
    if raw == "integer":
        return Type("int")
    if raw == "number":
        return Type("float")
    if raw == "boolean":
        return Type("bool")
    if raw == "string":
        return Type("datetime") if schema.get("format") == "date-time" else Type("str")
    if raw == "object" or raw is None:
        return Type("any")
    return Type("str")


def item_schema_name(response_schema: dict) -> str | None:
    results = (response_schema.get("properties") or {}).get("results")
    if not results:
        return None
    if "$ref" in results:
        return results["$ref"].rsplit("/", 1)[-1]
    if results.get("type") == "array":
        return (results.get("items") or {}).get("$ref", "").rsplit("/", 1)[-1] or None
    return None


def unwrap_paginated_alias(name: str | None, schemas: dict) -> str | None:
    # `PaginatedContentList` is declared as a bare `array of Content`; the SDK
    # carries the element type and gets the array from the envelope instead.
    if not name:
        return None
    target = schemas.get(name, {})
    if target.get("type") == "array" and "$ref" in (target.get("items") or {}):
        return target["items"]["$ref"].rsplit("/", 1)[-1]
    return name


def success_response(op: dict) -> tuple[int, dict]:
    for code in sorted(op.get("responses", {}), key=str):
        if str(code).startswith("2"):
            body = (op["responses"][code].get("content") or {}).get("application/json") or {}
            return int(code), body.get("schema") or {}
    return 200, {}


def classify(operation_id: str, query_params: list[Param]) -> str:
    if operation_id in FORCE_LIST:
        return "list"
    if operation_id in FORCE_SINGLE:
        return "single"
    if any(p.name == "page" for p in query_params):
        return "page"
    return "single"


def body_params(ref: str | None, schemas: dict) -> list[Param]:
    if not ref:
        return []
    schema = schemas.get(ref, {})
    required = set(schema.get("required") or [])
    out = []
    for name, prop in (schema.get("properties") or {}).items():
        if prop.get("readOnly"):
            continue
        out.append(
            Param(
                name=name,
                location="body",
                required=name in required,
                type=resolve_type(prop),
                description=(prop.get("description") or "").strip(),
            )
        )
    return sorted(out, key=lambda p: not p.required)


def flatten(node: Type, schemas: dict, seen: frozenset[str] = frozenset()) -> Type:
    # `--collapse-root-models` inlines every enum/alias schema, so a $ref to a
    # non-object schema has no class to point at and must become its own type.
    if node.kind == "array" and node.item is not None:
        return Type(
            "array",
            item=flatten(node.item, schemas, seen),
            min_items=node.min_items,
        )
    if node.kind != "ref" or node.ref is None or node.ref in seen:
        return node
    target = schemas.get(node.ref)
    if not target or target.get("properties") or target.get("additionalProperties"):
        return node
    return flatten(resolve_type(target), schemas, seen | {node.ref})


def build_param(raw: dict) -> Param:
    return Param(
        name=raw["name"],
        location=raw["in"],
        required=bool(raw.get("required") or raw["in"] == "path"),
        type=resolve_type(raw.get("schema") or {}),
        description=(raw.get("description") or "").strip(),
    )


def webhook_events(doc: dict) -> list[Webhook]:
    """Read the 3.1 `webhooks` block.

    Every declaration shares the WebhookPush envelope, so the event type is the
    only thing that distinguishes them and it is spelled out only in the
    description's worked example.
    """
    out = []
    for name, body in (doc.get("webhooks") or {}).items():
        post = body.get("post") or {}
        description = (post.get("description") or "").strip()
        found = re.findall(r'"type": "([a-z_]+\.[a-z_]+)"', description)
        if not found:
            raise ValueError(f"webhook {name} declares no event type in its example")
        schema = (post.get("requestBody") or {}).get("content", {}).get(
            "application/json", {}
        ).get("schema") or {}
        out.append(
            Webhook(
                name=name,
                event_type=found[0],
                payload=schema.get("$ref", "").rsplit("/", 1)[-1] or "WebhookPush",
                description=description,
            )
        )
    return out


def load(path: Path) -> Api:
    doc = yaml.safe_load(path.read_text())
    schemas = doc.get("components", {}).get("schemas", {})
    operations: list[Operation] = []

    for url, methods in doc.get("paths", {}).items():
        for http_method, raw in methods.items():
            if not isinstance(raw, dict) or "operationId" not in raw:
                continue
            operation_id = OPERATION_RENAMES.get(raw["operationId"], raw["operationId"])
            if "." not in operation_id:
                raise ValueError(f"operationId {operation_id!r} is not `resource.method`")
            resource, method = operation_id.split(".", 1)

            params = [build_param(p) for p in raw.get("parameters") or []]
            path_params = [p for p in params if p.location == "path"]
            query_params = [p for p in params if p.location == "query"]

            body_schema = (
                (raw.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
                or {}
            )
            body_ref = body_schema.get("$ref", "").rsplit("/", 1)[-1] or None
            status, response_schema = success_response(raw)
            if response_schema and set(response_schema.get("properties") or {}) - ENVELOPE_KEYS:
                raise ValueError(f"{operation_id}: unexpected non-envelope response shape")

            operations.append(
                Operation(
                    operation_id=operation_id,
                    raw_operation_id=raw["operationId"],
                    resource=snake(resource),
                    method=snake(method),
                    http_method=http_method.upper(),
                    path=url,
                    path_params=path_params,
                    query_params=query_params,
                    body=body_ref,
                    body_required=bool((raw.get("requestBody") or {}).get("required")),
                    body_fields=body_params(body_ref, schemas),
                    status=status,
                    item=unwrap_paginated_alias(item_schema_name(response_schema), schemas),
                    cardinality=classify(operation_id, query_params),
                    summary=(raw.get("summary") or "").strip(),
                    description=(raw.get("description") or "").strip(),
                )
            )

    error_codes = {}
    for status in (400, 401, 403, 404, 406, 429, 500, 503):
        schema = schemas.get(f"Error{status}", {})
        codes = (
            schema.get("properties", {}).get("error", {})
            .get("properties", {}).get("code", {}).get("enum")
        )
        if codes:
            error_codes[status] = list(codes)

    for operation in operations:
        for param in (*operation.path_params, *operation.query_params, *operation.body_fields):
            param.type = flatten(param.type, schemas)

    return Api(
        title=doc["info"]["title"],
        version=doc["info"]["version"],
        server=doc["servers"][0]["url"],
        description=doc["info"].get("description", ""),
        operations=sorted(operations, key=lambda o: (o.resource, o.method)),
        schemas=schemas,
        webhooks=sorted(webhook_events(doc), key=lambda w: w.event_type),
        error_codes=error_codes,
    )
