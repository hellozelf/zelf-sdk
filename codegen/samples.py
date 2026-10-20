import hashlib
import re

import models as models_module
from spec import Api, Operation, Type

ID_PREFIXES = {
    "AiAnalysis": "bod_",
    "AiAnalysisResult": "ban_",
    "Brand": "brd_",
    "BrandAccount": "cr_",
    "BrandCatalog": "brd_",
    "Comment": "com_",
    "CommentAuthor": "cr_",
    "Content": "con_",
    "ContentComment": "com_",
    "ContentCreator": "cr_",
    "ContentDiscovery": "sas_",
    "Creator": "cr_",
    "CreatorNested": "cr_",
    "CreatorSync": "csj_",
    "CreatorVetting": "bod_",
    "Detection": "aer_",
    "SubBrand": "brd_",
    "WebhookDelivery": "whd_",
    "WebhookSecret": "whsec_",
    "WebhookSubscription": "whs_",
}

FIELD_PREFIXES = {
    "analysis_id": "ban_",
    "brand_id": "brd_",
    "content_id": "con_",
    "creator_id": "cr_",
    "parent_brand_id": "brd_",
    "parent_comment_id": "com_",
    "secret_id": "whsec_",
    "subscription_id": "whs_",
    "vetting_id": "bod_",
}

ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
TIMESTAMP = "2026-01-01T00:00:00Z"

# Free strings in the spec that only ever hold one of a few values.
KNOWN_STRINGS = {
    "account_type": "tracked",
    "content_form": "VIDEO",
    "kind": "snapshot",
    "language": "en",
    "last_status": "SUCCESS",
    "mention_type": "content",
    "platform": "tiktok",
    "platform_handle": "zelfai",
    "platform_post_id": "7665460027683012345",
    "resource": "content",
    "scope": "CONTENT",
    "status": "COMPLETED",
    "sub_brand_type": "THEME",
    "username": "zelfai",
}

KNOWN_NUMBERS = {
    "earned_media_value_cents": 12500000,
    "follower_count": 412000,
    "interval_hours": 24,
    "item_count": 1,
    "max_items": 10,
    "page": 1,
    "total_engagement": 18400,
    "view_count": 327400000,
}


def token(seed: str, length: int = 16) -> str:
    """A stable sqids-looking suffix, so regenerating never churns the diff."""
    digest = hashlib.sha256(seed.encode()).digest()
    return "".join(ALPHABET[b % len(ALPHABET)] for b in digest[:length])


def identifier(model_name: str, field_name: str) -> str:
    prefix = FIELD_PREFIXES.get(field_name) or ID_PREFIXES.get(model_name) or "id_"
    return prefix + token(f"{model_name}.{field_name}")


def string_value(model_name: str, field_name: str) -> str:
    name = field_name.lower()
    if name in KNOWN_STRINGS:
        return KNOWN_STRINGS[name]
    if name == "id" or (name.endswith("_id") and name in FIELD_PREFIXES):
        return identifier(model_name, name)
    if name.endswith("_id"):
        # A foreign id, such as a platform's own post id.
        return token(f"{model_name}.{name}")
    if name.endswith("url") or name.endswith("uri"):
        return f"https://example.com/{model_name.lower()}/{name}"
    if name.endswith("_at") or name in ("timestamp", "created", "modified"):
        return TIMESTAMP
    if "email" in name:
        return "example@zelflive.com"
    if "username" in name or "handle" in name:
        return "zelfai"
    if "secret" in name:
        return "sk_zelf_wh_" + token(f"{model_name}.{name}", 24)
    if "format" in name:
        return "json"
    if "sha256" in name or "checksum" in name:
        return hashlib.sha256(f"{model_name}.{name}".encode()).hexdigest()
    return re.sub(r"[_.]", " ", name).strip().capitalize()


def number_value(field_name: str) -> int:
    name = field_name.lower()
    if name in KNOWN_NUMBERS:
        return KNOWN_NUMBERS[name]
    if "count" in name or name.endswith("s"):
        return 42
    if "page" in name:
        return 1
    if "hours" in name or "days" in name:
        return 24
    if "cents" in name:
        return 12500000
    return 7


def sample(
    node: Type,
    model_name: str,
    field_name: str,
    registry: dict,
    seen: frozenset[str],
):
    kind = node.kind
    if kind == "ref":
        return sample_named(node.ref, registry, seen)
    if kind == "array":
        if node.item is None:
            return []
        count = max(node.min_items, 1)
        return [
            sample(node.item, model_name, f"{field_name}_{i}" if i else field_name, registry, seen)
            for i in range(count)
        ]
    if kind == "enum":
        values = [v for v in (node.enum or []) if v is not None]
        return values[0] if values else ""
    if node.enum:
        # A numeric enum is typed as its scalar, so only a listed value round
        # trips through the generated model.
        return node.enum[0]
    if kind == "int":
        return number_value(field_name)
    if kind == "float":
        return 0.0425
    if kind == "bool":
        return True
    if kind == "datetime":
        return TIMESTAMP
    if kind == "any":
        # A multi-member oneOf loses its variants in the IR; the name does not.
        if field_name.lower() in KNOWN_STRINGS:
            return KNOWN_STRINGS[field_name.lower()]
        return {}
    return string_value(model_name, field_name)


def sample_named(name: str | None, registry: dict, seen: frozenset[str]):
    """One sample for a named schema, guarding against self-referencing models."""
    if name is None:
        return {}
    entry = registry.get(name)
    if entry is None:
        return {}
    if name in seen:
        # Self-referencing model: one level terminates, a second would not.
        return None
    if isinstance(entry, models_module.Enum):
        values = [v for v in entry.values if v is not None]
        return values[0] if values else ""
    return sample_model(entry, registry, seen | {name})


def sample_model(model, registry: dict, seen: frozenset[str] = frozenset()) -> dict:
    """Every field, required or not, so a round trip touches every accessor."""
    return {
        field.name: sample(field.type, model.name, field.name, registry, seen)
        for field in model.fields
    }


def build(api: Api) -> dict[str, dict]:
    model_list, enum_list = models_module.build(api)
    registry = {m.name: m for m in model_list} | {e.name: e for e in enum_list}
    return {
        m.name: sample_model(m, registry, frozenset({m.name}))
        for m in model_list
    }


def envelope(operation: Operation, rows: list) -> dict:
    """The success envelope the API wraps every 2xx body in."""
    body = {
        "log_id": "0ca57078-d810-4038-a1d7-02953ac7ce60",
        "timestamp": TIMESTAMP,
        "results": rows,
        "item_count": len(rows),
        "page": 1,
        "next": None,
        "previous": None,
    }
    if operation.cardinality != "page":
        body.pop("page")
        body.pop("next")
        body.pop("previous")
        body["page"] = 1
        body["next"] = None
        body["previous"] = None
    return body


def envelopes(api: Api, samples: dict[str, dict]) -> dict[str, dict]:
    """An envelope per operation, for the ones the spec publishes no example for."""
    out = {}
    for operation in api.operations:
        if operation.item is None:
            rows: list = []
        else:
            row = samples.get(operation.item)
            rows = [row] if row is not None else []
        out[operation.operation_id] = envelope(operation, rows)
    return out
