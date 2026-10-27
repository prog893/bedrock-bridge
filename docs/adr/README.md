# Architecture decision records

Each record states one decision, why it was made, and what it costs. Records
are not edited after acceptance except to change their status; a decision that
changes gets a new record that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](./0001-converse-only.md) | Converse is the only inference API | Accepted; revisit in #14 |
| [0002](./0002-no-claude-models.md) | The bridge does not serve Claude models | Accepted |
| [0003](./0003-drop-untranslatable-fields.md) | Drop request fields Converse cannot carry | Accepted |
| [0004](./0004-sourced-per-model-tables.md) | Per-model tables only when sourced | Accepted |
| [0005](./0005-fold-system-messages.md) | Fold system-role messages into user turns | Accepted |
| [0006](./0006-mint-tool-use-ids.md) | Mint response-side tool_use IDs | Accepted |
| [0007](./0007-error-mapping.md) | Map Bedrock errors to messages Claude Code recovers from | Accepted |
| [0008](./0008-no-silent-truncation.md) | No silent truncation of tool results | Accepted |
| [0009](./0009-implicit-caching-only.md) | Implicit prompt caching only by default | Accepted; opt-in explicit caching in #22 |
| [0010](./0010-distribution.md) | Homebrew from git tags; no PyPI, no bottles | Accepted |

## Template

```markdown
# NNNN. Title

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
```
