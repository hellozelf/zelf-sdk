import json
import os
import sys
from pathlib import Path

import changelog
import languages
import release
import shape
from spec import load

SDK = Path(__file__).resolve().parent.parent
LOCK = SDK / "spec" / "spec.lock"
CHANGELOG = SDK / "CHANGELOG.md"

ORDER = {changelog.NONE: 0, changelog.MINOR: 1, changelog.MAJOR: 2}


def current() -> dict:
    return shape.shape(load(release.SPEC))


def locked() -> dict | None:
    """The structural shape the last release was cut from."""
    if not LOCK.exists():
        return None
    return json.loads(LOCK.read_text())["shape"]


def locked_version() -> str | None:
    """The version that shape was cut at."""
    if not LOCK.exists():
        return None
    return json.loads(LOCK.read_text()).get("version")


def write_lock(state: dict, version: str) -> None:
    # Pretty-printed on purpose: the diff of this file in a pull request is a
    # readable account of exactly what moved in the API.
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "shape": state}
    LOCK.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def declared_bump(previous: str, declared: str) -> str:
    was = release.parts(previous)
    now = release.parts(declared)
    if now[0] != was[0]:
        return changelog.MAJOR
    if now[1] != was[1]:
        return changelog.MINOR
    return changelog.NONE


def emit(name: str, value: str) -> None:
    """Hand a value to the next workflow step, or to stdout when run locally."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        print(f"{name}={value}")
        return
    with open(target, "a") as fh:
        fh.write(f"{name}={value}\n")


def cmd_classify() -> int:
    """What kind of change this is, which decides whether anything releases.

    Three answers. `structural` means the API surface moved. `version-only`
    means it did not, but the declared version did, which is still a release
    because the version is the contract. `docs-only` means neither moved, so
    the clients are regenerated and nothing is tagged.
    """
    before, after = locked(), current()
    declared = release.sdk_version()

    if before is None:
        emit("kind", "structural")
        print("no lock file yet, treating this as the first release")
        return 0

    changes = changelog.diff(before, after)
    if not changes.empty:
        emit("kind", "structural")
        print(changelog.render(declared, changes))
        print(f"implied bump: {changes.bump}")
        return 0

    if (previous := _previous_version()) and previous != declared:
        emit("kind", "version-only")
        print(
            f"the API surface is unchanged, but the version moved {previous} -> {declared}"
        )
        return 0

    emit("kind", "docs-only")
    print("nothing moved but prose; regenerate and commit, then bump the patch")
    return 0


def cmd_check_spec() -> int:
    """The rules that hold before anything is regenerated.

    The bump the SDK declares has to be at least as large as the change to the
    surface deserves. The document's own version is recorded, not obeyed.
    """
    problems = []
    declared = release.sdk_version()

    before = locked()
    if before is not None and (previous := _previous_version()):
        after = current()
        changes = changelog.diff(before, after)
        stated = declared_bump(previous, declared)

        # The API versions its own compatibility in the path, so a new URL
        # version is what forces a major bump, not a removal inside the
        # current one.
        was_paths, now_paths = shape.path_versions(before), shape.path_versions(after)
        if now_paths != was_paths and stated != changelog.MAJOR:
            problems.append(
                f"the served path versions moved from {sorted(was_paths)} to "
                f"{sorted(now_paths)}; that is a major change, but {declared} "
                f"is a {stated} bump"
            )

        if changes.removed and stated != changelog.MAJOR:
            # Allowed, because the path version did not move, but a customer
            # calling this today will break, so it is said loudly.
            print(
                "::warning::this release removes part of "
                + f"{sorted(now_paths)[0] if now_paths else 'the API'}: "
                + "; ".join(changes.removed)
            )

    for line in problems:
        print(f"error: {line}")
    return 1 if problems else 0


def cmd_check_manifests() -> int:
    """Every client ships the one SDK version. Run after `make all`."""
    problems = release.check()
    for line in problems:
        print(f"error: {line}")
    return 1 if problems else 0


def _previous_version() -> str | None:
    """The version the lock was cut at.

    The lock records it, so this does not depend on how the changelog is
    formatted. The changelog is only consulted for a lock written before the
    version was stored.
    """
    if recorded := locked_version():
        return recorded
    if not CHANGELOG.exists():
        return None
    for line in CHANGELOG.read_text().splitlines():
        if line.startswith("## "):
            candidate = line[3:].strip()
            try:
                release.parts(candidate)
            except SystemExit:
                continue
            return candidate
    return None


def cmd_changelog() -> int:
    """Prepend this version's entry to CHANGELOG.md and refresh the lock."""
    before, after = locked(), current()
    version = release.sdk_version()

    if before is None or not released_before():
        # A diff against nothing is meaningless, so the opening entry lists the
        # whole surface instead. The lock may already exist without a release
        # having happened, which is why this asks the changelog and not the lock.
        entry = first_release(version, after)
        if f"\n## {version}\n" not in "\n" + CHANGELOG.read_text():
            _prepend(entry)
            print(entry)
        write_lock(after, version)
        return 0

    if before is not None:
        changes = changelog.diff(before, after)
        previous = _previous_version()
        entry = None
        if not changes.empty:
            entry = changelog.render(version, changes)
        elif previous and previous != version:
            # The surface did not move, but the version did. The release still
            # happens, because the version is what a caller pins to.
            entry = (
                f"## {version}\n\nNo change to the API surface. Released to "
                f"track the API version.\n"
            )
        if entry and f"\n## {version}\n" in "\n" + CHANGELOG.read_text():
            print(f"CHANGELOG.md already has an entry for {version}")
            entry = None
        if entry:
            _prepend(entry)
            print(entry)
    write_lock(after, version)
    return 0


def _prepend(entry: str) -> None:
    text = CHANGELOG.read_text()
    at = text.find("\n## ")
    head, tail = (text[: at + 1], text[at + 1 :]) if at != -1 else (text + "\n", "")
    CHANGELOG.write_text(f"{head}{entry}\n{tail}")


def released_before() -> bool:
    """Whether any version has shipped, which the changelog is the record of."""
    if not CHANGELOG.exists():
        return False
    return any(line.startswith("## ") for line in CHANGELOG.read_text().splitlines())


def first_release(version: str, state: dict) -> str:
    """The opening entry: the whole surface, since there is nothing to diff."""
    names = {"js": "TypeScript", "csharp": "C#"}
    clients = ", ".join(names.get(n, n.title()) for n in languages.RELEASED)

    by_resource: dict[str, list[str]] = {}
    for op in state["operations"]:
        resource, _, method = op["id"].partition(".")
        by_resource.setdefault(resource, []).append(method)

    lines = [
        f"## {version}",
        "",
        f"First release. {len(languages.RELEASED)} clients generated from the "
        f"published OpenAPI document, covering all "
        f"{len(state['operations'])} operations.",
        "",
        f"Clients: {clients}.",
        "",
        "### Operations",
        "",
    ]
    for resource in sorted(by_resource):
        methods = ", ".join(f"`{m}`" for m in sorted(by_resource[resource]))
        lines.append(f"- **{resource}**: {methods}")

    lines += ["", "### Webhook events", ""]
    for hook in sorted(state["webhooks"], key=lambda h: h["event_type"]):
        lines.append(f"- `{hook['event_type']}`")

    lines += [
        "",
        "### Types",
        "",
        f"- {len(state['models'])} models and {len(state['enums'])} enums, "
        f"generated from the document",
        f"- {len(state['error_codes'])} error codes, each with its own exception type",
        "",
        "### Client behaviour",
        "",
        "- The same resources and method names in every language",
        "- Cursor-free pagination with three bounds: everything, N pages, or N items",
        "- Typed errors carrying the API's error code and `log_id`",
        "- Retries honouring `Retry-After`; writes are never retried, "
        "because the API publishes no idempotency key",
        "- Webhook verification, typed events, a routing handler, and "
        "manifest downloads checked against the published SHA-256",
        "- `ZELF_API_KEY` and `ZELF_BASE_URL` are read from the environment",
        "",
    ]
    return "\n".join(lines)


def cmd_matrix() -> int:
    """What the release job should ensure exists, as JSON."""
    rows = [
        {
            "language": name,
            "version": release.version_for(name),
            "tag": f"{languages.TAG_PREFIX[name]}/v{release.version_for(name)}",
        }
        for name in languages.RELEASED
    ]
    payload = json.dumps(rows, separators=(",", ":"))
    emit("matrix", payload)
    print(payload)
    return 0


def cmd_lock() -> int:
    write_lock(current(), release.sdk_version())
    print(f"wrote {LOCK.relative_to(SDK)}")
    return 0


def cmd_bump() -> int:
    """Move the SDK version. The position is the second argument."""
    position = sys.argv[2] if len(sys.argv) > 2 else "patch"
    was = release.sdk_version()
    print(f"{was} -> {release.bump(position)}")
    return 0


COMMANDS = {
    "classify": cmd_classify,
    "check-spec": cmd_check_spec,
    "check-manifests": cmd_check_manifests,
    "changelog": cmd_changelog,
    "matrix": cmd_matrix,
    "lock": cmd_lock,
    "bump": cmd_bump,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: python codegen/pipeline.py [{'|'.join(COMMANDS)}]")
        raise SystemExit(2)
    raise SystemExit(COMMANDS[sys.argv[1]]())
