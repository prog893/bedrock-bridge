# 0006. Mint response-side tool_use IDs

- Status: Accepted
- Date: 2026-10-12 (#20)

## Context

Anthropic tool_use IDs are unique within a conversation, and Claude Code pairs tool results by ID. Some models number calls per response instead: GLM 5.3 names every call `call_0`. Passed through, repeated IDs made Claude Code repair its history on every request, and the model saw its earlier tool calls disappear.

## Decision

Give every response-side tool_use a fresh `toolu_bridge_<hex>` ID, on the streaming and buffered paths and on starts synthesized from a bare delta. Nothing maps back: Claude Code sends the minted ID in both the tool_use and the tool_result of the next request.

## Consequences

Sessions that already hold repeated IDs in their history stay broken; start a new session.
