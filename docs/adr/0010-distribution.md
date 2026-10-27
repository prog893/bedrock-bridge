# 0010. Homebrew from git tags; no PyPI, no bottles

- Status: Accepted
- Date: recorded 2026-10-27; the decision predates this record

## Context

The bridge is a small macOS CLI with pure-Python dependencies.

## Decision

Distribute through the `prog893/homebrew-tap` formula, built with `virtualenv_install_with_resources` from a git tag of this repo. No PyPI package. No bottles: a third-party tap gets none unless it hosts them itself, which is not worth the build pipeline before 1.0.

## Consequences

Each release updates the formula's tag and commit; see [releasing.md](../releasing.md). Dependency changes require regenerating the formula's resource blocks.
