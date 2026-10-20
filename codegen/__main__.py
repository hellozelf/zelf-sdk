import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import emit_conformance  # noqa: E402
import emit_python  # noqa: E402
import emit_go  # noqa: E402
import emit_csharp  # noqa: E402
import emit_java  # noqa: E402
import emit_ruby  # noqa: E402
import emit_rust  # noqa: E402
import emit_ts  # noqa: E402
import spec  # noqa: E402

SDK = ROOT.parent
SPEC = SDK / "spec" / "openapi.yaml"


def main() -> int:
    targets = sys.argv[1:] or ["python", "js", "go", "rust", "ruby", "csharp", "java"]
    api = spec.load(SPEC)
    print(f"{api.title} {api.version}: {len(api.operations)} operations, {len(api.resources)} resources")
    if "python" in targets:
        emit_python.emit(api, SPEC, SDK / "python", ROOT / "templates" / "python")
        emit_conformance.python(api, SDK / "python")
        print("  python -> python/zelf")
    if "js" in targets:
        emit_ts.emit(api, SPEC, SDK / "js", ROOT / "templates" / "js")
        emit_conformance.js(api, SDK / "js")
        print("  js     -> js/src")
    if "rust" in targets:
        emit_rust.emit(api, SPEC, SDK / "rust", ROOT / "templates" / "rust")
        emit_conformance.rust(api, SDK / "rust")
        print("  rust   -> rust/src")
    if "java" in targets:
        emit_java.emit(api, SPEC, SDK / "java", ROOT / "templates" / "java")
        emit_conformance.java(api, SDK / "java")
        print("  java   -> java/src/main/java")
    if "csharp" in targets:
        emit_csharp.emit(api, SPEC, SDK / "csharp", ROOT / "templates" / "csharp")
        emit_conformance.csharp(api, SDK / "csharp")
        print("  csharp -> csharp/src")
    if "ruby" in targets:
        emit_ruby.emit(api, SPEC, SDK / "ruby", ROOT / "templates" / "ruby")
        print("  ruby   -> ruby/lib")
    if "go" in targets:
        emit_go.emit(api, SPEC, SDK / "go", ROOT / "templates" / "go")
        # Needs emit_go's output: the union tests are derived from it.
        emit_conformance.go(api, SDK / "go")
        print("  go     -> go")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
