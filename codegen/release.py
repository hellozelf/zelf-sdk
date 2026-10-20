import json
import re
from pathlib import Path

SDK = Path(__file__).resolve().parent.parent
SPEC = SDK / "spec" / "openapi.yaml"

# X.Y belong to the API and arrive in the spec. Z belongs to the SDK and lives
# in each manifest, so a client can ship a fix of its own without the API
# moving. A spec bump resets Z, which is what keeps the clients level.
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

SOURCES = {
    "python": (
        SDK / "python" / "pyproject.toml",
        re.compile(r'(?m)^version = "([^"]+)"'),
    ),
    "js": (SDK / "js" / "package.json", None),
    "rust": (SDK / "rust" / "Cargo.toml", re.compile(r'(?m)^version = "([^"]+)"')),
    "ruby": (
        SDK / "ruby" / "lib" / "zelf" / "version.rb",
        re.compile(r"VERSION = '([^']+)'"),
    ),
    "csharp": (
        SDK / "csharp" / "src" / "Zelf.csproj",
        re.compile(r"<Version>([^<]+)</Version>"),
    ),
    "java": (
        SDK / "java" / "pom.xml",
        re.compile(r"<artifactId>zelf-sdk</artifactId>\s*<version>([^<]+)</version>"),
    ),
    "go": (SDK / "go" / "client.go", re.compile(r'const Version = "([^"]+)"')),
}


def spec_version() -> str:
    """`info.version` from the document, which owns X and Y."""
    found = re.search(r"(?m)^  version: (\S+)", SPEC.read_text())
    if not found:
        raise SystemExit(f"{SPEC} has no info.version")
    return found.group(1)


def manifest_version(language: str) -> str | None:
    path, pattern = SOURCES[language]
    if not path.exists():
        return None
    if pattern is None:
        return json.loads(path.read_text()).get("version")
    found = pattern.search(path.read_text())
    return found.group(1) if found else None


def parts(version: str) -> tuple[int, int, int]:
    found = SEMVER.match(version)
    if not found:
        raise SystemExit(f"{version} is not a three-part semantic version")
    return tuple(int(n) for n in found.groups())


def version_for(language: str) -> str:
    """What this client's manifest should say.

    The spec sets X.Y. Z carries over only while X.Y has not moved, so a
    client-only fix survives a regeneration but a spec bump levels everyone.
    """
    major, minor, _ = parts(spec_version())
    current = manifest_version(language)
    patch = 0
    if current:
        was_major, was_minor, was_patch = parts(current)
        if (was_major, was_minor) == (major, minor):
            patch = was_patch
    return f"{major}.{minor}.{patch}"


def check() -> list[str]:
    """The two rules, as a list of complaints. Empty means the tree is legal."""
    problems = []
    declared = spec_version()
    major, minor, patch = parts(declared)

    if patch != 0:
        problems.append(
            f"spec/openapi.yaml declares {declared}; the patch position belongs to "
            f"the SDK, so the spec must end in .0"
        )

    for language in SOURCES:
        current = manifest_version(language)
        if current is None:
            continue
        was_major, was_minor, _ = parts(current)
        if (was_major, was_minor) != (major, minor):
            problems.append(
                f"{language} is at {current} but the spec is at {declared}; "
                f"major and minor belong to the API, so only the patch may differ"
            )
    return problems


if __name__ == "__main__":
    found = check()
    for line in found:
        print(f"error: {line}")
    raise SystemExit(1 if found else 0)
