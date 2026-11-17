import json
import re

# The documents a run's `result.download_url` points at. The AI pipeline writes
# them, not a serializer, so a field can come back null, missing, or as a
# decimal where the spec says integer. Every SDK decodes them softly; nothing
# else in the API is touched.
REPORT_ROOTS = ("AiAnalysisReport", "AdvancedAiAnalysisReport", "CreatorVettingReport")

REF = re.compile(r"#/components/schemas/(\w+)")


def refs(node) -> set[str]:
    return set(REF.findall(json.dumps(node)))


def report_schemas(doc: dict) -> set[str]:
    """The report roots and every schema nested under them.

    Fails when one of them is also used by an endpoint, a webhook or another
    schema, so the soft rules can never reach a regular response or a request.
    """
    schemas = doc["components"]["schemas"]
    seen: set[str] = set()
    queue = [name for name in REPORT_ROOTS if name in schemas]
    while queue:
        name = queue.pop()
        if name not in seen:
            seen.add(name)
            queue.extend(refs(schemas[name]))
    outside = refs(doc.get("paths", {})) | refs(doc.get("webhooks", {}))
    for name, schema in schemas.items():
        if name not in seen:
            outside |= refs(schema)
    shared = sorted(seen & outside)
    if shared:
        raise SystemExit(f"report schemas used outside a report: {shared}")
    return seen


def soften_property(prop: dict) -> dict:
    """Make one property accept null, and a decimal where it says integer."""
    if "$ref" in prop or "allOf" in prop:
        inner = {k: v for k, v in prop.items() if k != "description"}
        described = {"description": prop["description"]} if "description" in prop else {}
        return {**described, "anyOf": [inner, {"type": "null"}]}
    if "anyOf" in prop or "oneOf" in prop:
        key = "anyOf" if "anyOf" in prop else "oneOf"
        members = [m for m in prop[key] if m.get("type") != "null"]
        rest = {k: v for k, v in prop.items() if k != key}
        return {**rest, "anyOf": [*members, {"type": "null"}]}
    kind = prop.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if "integer" in kinds:
        kinds = [k for k in kinds if k != "integer"] + ["integer", "number"]
    return {**prop, "type": [k for k in kinds if k != "null"] + ["null"]}


def soften(doc: dict) -> None:
    """Rewrite the report schemas in place: nothing required, every field nullable."""
    schemas = doc["components"]["schemas"]
    for name in report_schemas(doc):
        schema = schemas[name]
        schema.pop("required", None)
        props = schema.get("properties") or {}
        for key, prop in props.items():
            props[key] = soften_property(prop)
