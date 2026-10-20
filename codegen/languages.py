# The clients the release pipeline publishes. Nothing in the workflows names a
# language; they read this. Adding one means appending here and copying a
# publish workflow, with no orchestration change.
RELEASED = ("python", "js", "rust", "ruby", "csharp", "go")

# Every client that is generated, released or not. An unreleased client still
# tracks the version, so it is already correct the day it ships.
ALL = ("python", "js", "go", "rust", "ruby", "java", "csharp")

# The tag prefix each release carries, and the registry behind it.
TAG_PREFIX = {
    "python": "py",
    "js": "js",
    "go": "go",
    "rust": "rust",
    "ruby": "ruby",
    "java": "java",
    "csharp": "csharp",
}
