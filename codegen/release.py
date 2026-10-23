import json
import re
from pathlib import Path

SDK = Path(__file__).resolve().parent.parent
SPEC = SDK / "spec" / "openapi.yaml"
VERSION_FILE = SDK / "spec" / "sdk-version.txt"

# The SDK owns its whole version and this file is the only place it is set.
# The spec's own version is recorded beside the clients as SPEC_VERSION rather
# than deriving theirs, so correcting a description ships as a patch instead of
# moving nine clients a minor for prose the API never changed.
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
    """`info.version` from the document, recorded by the clients, not their own."""
    found = re.search(r"(?m)^  version: (\S+)", SPEC.read_text())
    if not found:
        raise SystemExit(f"{SPEC} has no info.version")
    return found.group(1)


def sdk_version() -> str:
    """The version every client ships at."""
    if not VERSION_FILE.exists():
        raise SystemExit(f"{VERSION_FILE} is missing")
    return VERSION_FILE.read_text().strip()


def bump(position: str) -> str:
    """Move the SDK version and write it back. Returns the new version."""
    major, minor, patch = parts(sdk_version())
    if position == "major":
        major, minor, patch = major + 1, 0, 0
    elif position == "minor":
        minor, patch = minor + 1, 0
    elif position == "patch":
        patch += 1
    else:
        raise SystemExit(f"{position} is not major, minor or patch")
    moved = f"{major}.{minor}.{patch}"
    VERSION_FILE.write_text(f"{moved}\n")
    return moved


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
    """What this client's manifest should say: the one version, for all of them."""
    return sdk_version()


def check() -> list[str]:
    """The one rule, as a list of complaints. Empty means the tree is legal."""
    problems = []
    declared = sdk_version()
    parts(declared)

    for language in SOURCES:
        current = manifest_version(language)
        if current is None:
            continue
        if current != declared:
            problems.append(
                f"{language} is at {current} but the SDK is at {declared}; "
                f"every client ships the version in spec/sdk-version.txt"
            )
    return problems


if __name__ == "__main__":
    found = check()
    for line in found:
        print(f"error: {line}")
    raise SystemExit(1 if found else 0)
