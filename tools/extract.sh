#!/usr/bin/env bash
# Copies this directory into a standalone git repository.
#
#   bash tools/extract.sh /tmp/zelf-sdk
#
# `client/` is gitignored by the monorepo, so there is no history to carry and
# `git subtree split` is not an option. A fresh `git init` is the whole story.
#
# This script does not create or push anything. It prints the command to do so.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${1:-}"

if [[ -z "$dest" ]]; then
    echo "usage: bash tools/extract.sh <destination>" >&2
    exit 64
fi
if [[ -e "$dest" ]]; then
    echo "error: $dest already exists; pick a path that does not" >&2
    exit 1
fi

mkdir -p "$dest"
rsync -a \
    --exclude '.git/' \
    --exclude '.tools/' \
    --exclude 'tools/extract.sh' \
    --exclude 'js/node_modules/' \
    --exclude 'js/dist/' \
    --exclude 'js/coverage/' \
    --exclude 'rust/target/' \
    --exclude 'java/target/' \
    --exclude 'csharp/src/obj/' \
    --exclude 'csharp/src/bin/' \
    --exclude 'csharp/tests/obj/' \
    --exclude 'csharp/tests/bin/' \
    --exclude 'python/.venv/' \
    --exclude 'python/.pytest_cache/' \
    --exclude 'python/.ruff_cache/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'go/cover.out' \
    --exclude '.DS_Store' \
    "$here/" "$dest/"

# tools/ exists only to hold this script, so it should not ship.
rmdir "$dest/tools" 2>/dev/null || true

git -C "$dest" init -q -b main
git -C "$dest" add -A

# A build artifact that slipped past .gitignore would be committed forever, so
# refuse rather than let that happen quietly.
if staged=$(git -C "$dest" diff --cached --name-only | grep -E '(^|/)(node_modules|target|dist|\.venv|obj|bin|\.tools)(/|$)'); then
    echo "error: build artifacts were staged:" >&2
    echo "$staged" | sed 's/^/  /' >&2
    exit 1
fi

git -C "$dest" commit -q -m "Initial commit

Eight generated clients for the Zelf API, built from the published OpenAPI
document. See docs/contributing.md for how the generator works."

files=$(git -C "$dest" ls-files | wc -l | tr -d ' ')
size=$(du -sh "$dest" | cut -f1)
echo "Staged $files files into $dest ($size)."
echo
echo "To publish it:"
echo "  gh repo create hellozelf/zelf-sdk --public --source=$dest --push"
echo
echo "Then tag the Go submodule so 'go get' resolves:"
echo "  git -C $dest tag go/v$(cat "$here/VERSION")"
echo "  git -C $dest push --tags"
