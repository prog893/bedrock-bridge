# 0005. Fold system-role messages into user turns

- Status: Accepted
- Date: 2026-09-18 (#6)

## Context

Claude Code 2.x sends `role: "system"` entries inside `messages`, including its `# Environment` block. Converse has no system role in `messages`: a trailing entry fails ("requires the last turn in the conversation to be a user message"), a mid-history one fails ("This model doesn't support system messages"). Moving them into the top-level `system` field would also work, but would rewrite the start of every request whenever a new entry appears.

## Decision

Fold each system-role entry into the adjacent user turn as a `<system-reminder>`-tagged text block (`translate._fold_system_messages`). Drop entries with no text.

## Consequences

- History stays append-only. Measured 2026-10-27 on three consecutive requests: Claude Code keeps these entries at their position in history, and each translated Converse request begins with the previous one unchanged, so implicit prompt caching is not disturbed.
- The model sees operator context in the same tagged shape Claude Code already uses inside user turns.
