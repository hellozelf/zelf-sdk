import re
from dataclasses import dataclass, field as dataclass_field

from spec import Api, Type, flatten, resolve_type

# These are hand written in every SDK: one class per status with the error
# codes attached, which a generated struct cannot express.
HAND_WRITTEN = re.compile(r"^Error\d{3}$")
SKIP = re.compile(r"^Paginated.*List$")


@dataclass
class Field:
    name: str
    type: Type
    required: bool
    nullable: bool
    read_only: bool
    description: str = ""


@dataclass
class Model:
    name: str
    description: str
    fields: list[Field] = dataclass_field(default_factory=list)


@dataclass
class Enum:
    name: str
    values: list[str]
    description: str = ""


def nullable(schema: dict) -> bool:
    kind = schema.get("type")
    if isinstance(kind, list) and "null" in kind:
        return True
    for member in schema.get("anyOf") or schema.get("oneOf") or []:
        if isinstance(member, dict) and member.get("type") == "null":
            return True
    return False


def unwrap(schema: dict) -> dict:
    """Collapse the single-member allOf and anyOf wrappers the spec uses."""
    for key in ("allOf", "anyOf", "oneOf"):
        members = schema.get(key)
        if not isinstance(members, list):
            continue
        concrete = [m for m in members if isinstance(m, dict) and m.get("type") != "null"]
        if len(concrete) == 1:
            merged = {k: v for k, v in schema.items() if k != key}
            merged.pop("description", None) if "description" in concrete[0] else None
            return unwrap({**concrete[0], **merged})
    return schema


def build(api: Api) -> tuple[list[Model], list[Enum]]:
    models: list[Model] = []
    enums: list[Enum] = []

    for name, raw in sorted(api.schemas.items()):
        if SKIP.match(name) or HAND_WRITTEN.match(name):
            continue
        schema = unwrap(raw)
        if schema.get("enum"):
            values = [v for v in schema["enum"] if v is not None]
            # Only a string enum can be emitted as named members; a numeric one
            # is carried as its scalar type instead.
            if all(isinstance(v, str) for v in values):
                enums.append(
                    Enum(
                        name=name,
                        values=values,
                        description=(schema.get("description") or "").strip(),
                    )
                )
            continue
        properties = schema.get("properties")
        if not properties:
            # A bare scalar or array alias carries no shape worth a class.
            continue
        required = set(schema.get("required") or [])
        models.append(
            Model(
                name=name,
                description=(schema.get("description") or "").strip(),
                fields=[
                    Field(
                        name=prop_name,
                        # A $ref to a scalar alias (a nullable numeric enum,
                        # say) has no class to point at, so resolve it to the
                        # type it stands for.
                        type=flatten(resolve_type(unwrap(prop)), api.schemas),
                        required=prop_name in required,
                        nullable=nullable(prop) or nullable(unwrap(prop)),
                        read_only=bool(prop.get("readOnly")),
                        description=(prop.get("description") or "").strip(),
                    )
                    for prop_name, prop in properties.items()
                ],
            )
        )
    return models, enums


def inline_enums(models: list[Model], enums: list[Enum]) -> dict[tuple[str, ...], str]:
    """Map each distinct enum value set onto the named type that holds it."""
    out = {tuple(e.values): e.name for e in enums}
    for model in models:
        for field in model.fields:
            node = field.type
            if node.kind == "array" and node.item:
                node = node.item
            if node.kind == "enum" and node.enum:
                out.setdefault(tuple(node.enum), f"{model.name}{field.name.title().replace('_', '')}")
    return out
