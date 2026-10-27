# 0002. The bridge does not serve Claude models

- Status: Accepted
- Date: recorded 2026-10-27; the decision predates this record

## Context

Claude Code speaks Bedrock natively (`CLAUDE_CODE_USE_BEDROCK=1`) for Claude models. Routing Claude through the bridge adds a hop and loses features the bridge drops on the way to Converse.

## Decision

Preflight refuses Anthropic model IDs (`anthropic.*` and their inference-profile forms) for every slot and prints the native setup instead.

## Consequences

- The bridge only has to be correct for non-Claude models.
- The e2e grader's judge must reach Claude without the bridge, which also keeps the judge independent of the code under test.
