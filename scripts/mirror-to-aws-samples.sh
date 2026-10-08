#!/usr/bin/env bash
# Mirror this repo into a local checkout of aws-samples/sample-apj-sup-sa under
# ai-coding-assistants/bedrock-bridge/. Development stays here on prog893; the
# aws-samples copy is a mirror only.
#
# Usage:
#   scripts/mirror-to-aws-samples.sh /path/to/sample-apj-sup-sa
#
# What it does:
#   1. Copies tracked files at their current working-tree content (no caches,
#      no .venv, no untracked junk; `git ls-files` defines the set).
#   2. Drops files that should not live in the mirror:
#        - LICENSE         -> the subdir inherits the repo-root MIT-0, matching
#                             how several sibling projects already omit theirs.
#        - .github/        -> workflows and the PR template only fire from a
#                             repo root; dead weight in a monorepo subdir.
#        - CONTRIBUTING.md -> dev-process doc tied to the personal repo (clone
#                             URL, the dropped PR template, the pre-commit hook).
#        - scripts/mirror-to-aws-samples.sh -> this tool itself.
#   3. Rewrites README.md for the mirror: removes the Homebrew install block
#      (personal tap is not advertised as canonical from an AWS-owned repo;
#      delimited by `mirror:brew` markers upstream), retitles the H1, and
#      repoints the CONTRIBUTING and LICENSE links. Exits nonzero if any anchor
#      text is missing, so README edits upstream cannot silently skip a rewrite.
#
# Refuses to run if the destination subdir has uncommitted changes, since each
# run deletes and recreates it.
#
# It does NOT commit, push, fork, or open a PR. Outward steps are manual.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_ROOT="${1:-}"
SUBDIR="ai-coding-assistants/bedrock-bridge"

if [[ -z "$DEST_ROOT" ]]; then
  echo "usage: $0 /path/to/sample-apj-sup-sa" >&2
  exit 2
fi
if [[ ! -d "$DEST_ROOT/.git" ]]; then
  echo "error: $DEST_ROOT is not a git checkout (expected the aws-samples clone)" >&2
  exit 2
fi
if [[ ! -d "$DEST_ROOT/ai-coding-assistants" ]]; then
  echo "error: $DEST_ROOT has no ai-coding-assistants/ (wrong repo?)" >&2
  exit 2
fi

DEST="$DEST_ROOT/$SUBDIR"

echo "src:  $SRC"
echo "dest: $DEST"

# The wipe below is permanent for anything not committed in the aws-samples
# checkout, so require a clean subdir first.
if [[ -n "$(git -C "$DEST_ROOT" status --porcelain -- "$SUBDIR")" ]]; then
  echo "error: $SUBDIR has uncommitted changes in $DEST_ROOT; commit or stash them first" >&2
  git -C "$DEST_ROOT" status --short -- "$SUBDIR" >&2
  exit 1
fi

# Fresh tree every run: tracked files only, current working-tree content.
rm -rf "$DEST"
mkdir -p "$DEST"
git -C "$SRC" ls-files -z | tar --null -C "$SRC" -T - -cf - | tar -x -C "$DEST"

# Files that should not exist in the mirror.
rm -f "$DEST/LICENSE"
rm -rf "$DEST/.github"
rm -f "$DEST/CONTRIBUTING.md"
rm -f "$DEST/scripts/mirror-to-aws-samples.sh"

# README transforms for the mirror:
#   - give the H1 a descriptive title (the personal repo keeps the bare package
#     name; aws-samples siblings use descriptive titles).
#   - drop the Homebrew block entirely (uv/uvx is the only install shown);
#     delimited by the mirror:brew markers, with one trailing blank line.
#   - repoint the two links to files this script drops: CONTRIBUTING.md -> the
#     upstream personal repo; the relative ./LICENSE -> the inherited
#     repo-root MIT-0.
UPSTREAM="https://github.com/prog893/bedrock-bridge"
python3 - "$DEST/README.md" "$UPSTREAM" <<'PY'
import sys

path, upstream = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()

start = end = None
for i, line in enumerate(lines):
    if "mirror:brew start" in line:
        start = i
    elif "mirror:brew end" in line:
        end = i
        break

def fail(msg):
    sys.exit(f"error: README.md {msg}; mirror left half-rewritten, do not commit it")

if start is None or end is None:
    fail("is missing the mirror:brew start/end markers")
# Drop the marked block; also swallow one blank line that followed the end
# marker so the section doesn't gain a double gap.
stop = end + 1
if stop < len(lines) and lines[stop].strip() == "":
    stop += 1
del lines[start:stop]

text = "".join(lines)

def replace_once(old, new):
    global text
    if old not in text:
        fail(f"no longer contains {old!r}")
    text = text.replace(old, new, 1)

# Descriptive H1 for the mirror; keeps the package name in the subtitle line.
replace_once(
    "# bedrock-bridge\n",
    "# Claude Code on non-Claude Bedrock models (bedrock-bridge)\n",
)
# CONTRIBUTING.md is not mirrored: link the canonical copy upstream.
replace_once("(./CONTRIBUTING.md)", f"({upstream}/blob/main/CONTRIBUTING.md)")
# LICENSE is not mirrored: the subdir inherits the repo-root MIT-0.
replace_once(
    "MIT. See [LICENSE](./LICENSE).",
    "Licensed under MIT-0, inherited from the repository [LICENSE](../../LICENSE).",
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
PY

echo
echo "Mirrored. Files in $SUBDIR:"
git -C "$DEST_ROOT" status --porcelain "$SUBDIR" | sed 's/^/  /' || true
echo
echo "Next (manual): review the diff, then commit/push/PR from the aws-samples checkout."
