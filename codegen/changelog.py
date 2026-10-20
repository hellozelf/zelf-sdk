from dataclasses import dataclass, field

import shape
from spec import Api

MAJOR, MINOR, NONE = "major", "minor", "none"


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    @property
    def bump(self) -> str:
        """The smallest bump this diff is allowed to ship under.

        Anything a caller could already be relying on counts as breaking:
        something taken away, or a rule tightened so code that passed before
        now fails.
        """
        if self.removed or any("now required" in c for c in self.changed):
            return MAJOR
        if self.added or self.changed:
            return MINOR
        return NONE


def index(rows: list[dict], key: str = "name") -> dict:
    return {row[key]: row for row in rows}


def params_of(op: dict) -> dict:
    return index(op["query_params"] + op["body_fields"] + op["path_params"])


def diff_operations(old: dict, new: dict, out: Diff) -> None:
    before, after = index(old["operations"], "id"), index(new["operations"], "id")

    for op_id in sorted(set(after) - set(before)):
        op = after[op_id]
        out.added.append(f"`{op_id}` ({op['http_method'].upper()} {op['path']})")
    for op_id in sorted(set(before) - set(after)):
        out.removed.append(f"`{op_id}`")

    for op_id in sorted(set(before) & set(after)):
        was, now = params_of(before[op_id]), params_of(after[op_id])
        for name in sorted(set(now) - set(was)):
            out.added.append(f"`{op_id}`: `{name}`{described(now[name])}")
        for name in sorted(set(was) - set(now)):
            out.removed.append(f"`{op_id}`: `{name}`")
        for name in sorted(set(was) & set(now)):
            if not was[name]["required"] and now[name]["required"]:
                out.changed.append(f"`{op_id}`: `{name}` is now required")
            elif was[name]["required"] and not now[name]["required"]:
                out.changed.append(f"`{op_id}`: `{name}` is no longer required")
            if was[name]["type"] != now[name]["type"]:
                out.changed.append(f"`{op_id}`: `{name}` changed type")


def diff_models(old: dict, new: dict, out: Diff) -> None:
    before, after = index(old["models"]), index(new["models"])

    for name in sorted(set(after) - set(before)):
        out.added.append(f"`{name}`")
    for name in sorted(set(before) - set(after)):
        out.removed.append(f"`{name}`")

    for name in sorted(set(before) & set(after)):
        was, now = index(before[name]["fields"]), index(after[name]["fields"])
        for f in sorted(set(now) - set(was)):
            out.added.append(f"`{name}.{f}`")
        for f in sorted(set(was) - set(now)):
            out.removed.append(f"`{name}.{f}`")
        for f in sorted(set(was) & set(now)):
            if was[f]["nullable"] != now[f]["nullable"]:
                state = "now nullable" if now[f]["nullable"] else "no longer nullable"
                out.changed.append(f"`{name}.{f}` is {state}")
            if was[f]["type"] != now[f]["type"]:
                out.changed.append(f"`{name}.{f}` changed type")


def diff_enums(old: dict, new: dict, out: Diff) -> None:
    before, after = index(old["enums"]), index(new["enums"])

    for name in sorted(set(after) - set(before)):
        out.added.append(f"`{name}`")
    for name in sorted(set(before) - set(after)):
        out.removed.append(f"`{name}`")

    for name in sorted(set(before) & set(after)):
        was, now = set(before[name]["values"]), set(after[name]["values"])
        for value in sorted(now - was):
            out.added.append(f"`{name}`: `{value}`")
        for value in sorted(was - now):
            out.removed.append(f"`{name}`: `{value}`")


def described(param: dict) -> str:
    kind = param["type"].get("kind", "")
    return f" ({kind})" if kind and kind != "any" else ""


def diff(before: dict, after: dict) -> Diff:
    """Compare two structural shapes.

    Shapes rather than documents, so the previous state can come from
    `spec/spec.lock` instead of digging the old file out of git.
    """
    out = Diff()
    diff_operations(before, after, out)
    diff_models(before, after, out)
    diff_enums(before, after, out)
    return out


def diff_api(before: Api, after: Api) -> Diff:
    return diff(shape.shape(before), shape.shape(after))


def render(version: str, changes: Diff) -> str:
    lines = [f"## {version}", ""]
    for heading, rows in (
        ("Added", changes.added),
        ("Changed", changes.changed),
        ("Removed", changes.removed),
    ):
        if not rows:
            continue
        lines.append(f"### {heading}")
        lines.extend(f"- {row}" for row in rows)
        lines.append("")
    return "\n".join(lines)
