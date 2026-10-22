import json
from pathlib import Path

from naming import camel, go_pascal, pascal, snake
from spec import Api, Operation

# C# suffixes every call, Rust reaches a resource through a method rather than
# an attribute, and Go writes initialisms in full caps. The shape each client
# uses is decided by its own emitter, so the spelling is recorded here once
# instead of being re-derived by whoever reads it.
LANGUAGES = ("python", "typescript", "go", "rust", "ruby", "csharp", "java")


def symbols(op: Operation) -> dict[str, dict[str, str]]:
    resource, method = op.resource, op.method
    return {
        "python": {"resource": snake(resource), "method": snake(method)},
        "typescript": {"resource": snake(resource), "method": camel(method)},
        "go": {"resource": go_pascal(resource), "method": go_pascal(method)},
        "rust": {"resource": snake(resource), "method": snake(method)},
        "ruby": {"resource": snake(resource), "method": snake(method)},
        "csharp": {
            "resource": pascal(resource),
            "method": f"{pascal(method)}Async",
        },
        "java": {"resource": camel(resource), "method": camel(method)},
    }


def emit(api: Api, target: Path) -> None:
    """Write the symbol each client exposes for every operation.

    The developer portal renders call snippets from this rather than from its
    own copy of the naming rules, so a renamed operation reaches the docs with
    the clients instead of drifting from them.
    """
    manifest = {
        "version": api.version,
        "operations": {
            op.operation_id: {
                "cardinality": op.cardinality,
                "symbols": symbols(op),
            }
            for op in api.operations
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
