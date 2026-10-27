# 0008. No silent truncation of tool results

- Status: Accepted
- Date: recorded 2026-10-27; the decision predates this record

## Context

Large `tool_result` blocks (big file reads, many screenshots) push requests past Bedrock's body-size cap. Truncating them in the bridge would keep requests under the cap.

## Decision

Do not truncate. Let the request fail and map the error so Claude Code compacts ([0007](./0007-error-mapping.md)).

## Consequences

The user sees a clear failure with a recovery path instead of a model that silently works from partial data.
