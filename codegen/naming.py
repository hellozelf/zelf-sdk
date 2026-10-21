import re

# Every operationId is `resource.method`, which maps straight onto
# `client.<resource>.<method>()`, so nothing needs renaming. Kept as a seam for
# the day the spec disagrees with a client again.
OPERATION_RENAMES: dict[str, str] = {}


# The envelope always wraps `results` in an array, even for single-object reads,
# so cardinality cannot be read off the response schema. `page` in the query
# params marks a real paginated list; the rest are classified here.
# An `x-zelf-cardinality` extension in the spec would remove this table.
FORCE_LIST = {
    "brands.catalog_categories",
    "webhooks.list_events",
    "brand_accounts.add",
    "brand_accounts.remove",
    "brand_accounts.list",
}
FORCE_SINGLE = {
    "content.statistics",
    "ai_analysis.content_statistics",
    "creator_vetting.content_statistics",
    "usage.retrieve",
}

PYTHON_KEYWORDS = {
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
    "None",
    "True",
    "False",
    "match",
    "case",
}

GO_KEYWORDS = {
    "break",
    "case",
    "chan",
    "const",
    "continue",
    "default",
    "defer",
    "else",
    "fallthrough",
    "for",
    "func",
    "go",
    "goto",
    "if",
    "import",
    "interface",
    "map",
    "package",
    "range",
    "return",
    "select",
    "struct",
    "switch",
    "type",
    "var",
}

INITIALISMS = {"id", "url", "api", "ai", "http", "json", "uuid", "sha256", "ndjson"}


def snake(name: str) -> str:
    # `state!` is drf-restflow's negation suffix; the spec spells the same idea
    # as `mention_type_not` elsewhere, so normalise onto that.
    name = re.sub(r"!$", "_not", name)
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"_+", "_", name).strip("_").lower()


def pascal(name: str) -> str:
    return "".join(
        part[:1].upper() + part[1:] for part in snake(name).split("_") if part
    )


def camel(name: str) -> str:
    out = pascal(name)
    return out[:1].lower() + out[1:]


def go_pascal(name: str) -> str:
    parts = [p for p in snake(name).split("_") if p]
    return "".join(
        p.upper() if p in INITIALISMS else p[:1].upper() + p[1:] for p in parts
    )


def py_param(name: str) -> str:
    out = snake(name)
    return out + "_" if out in PYTHON_KEYWORDS else out


def go_field(name: str) -> str:
    out = go_pascal(name)
    return out + "_" if out.lower() in GO_KEYWORDS else out


def enum_member(value: str, fallback: str = "Empty") -> str:
    """A language identifier for an enum value.

    The API uses `-posted_at` for descending sorts and `""` for "not set
    yet", neither of which is an identifier anywhere.
    """
    return pascal(value.replace("-", "desc_")) or fallback
