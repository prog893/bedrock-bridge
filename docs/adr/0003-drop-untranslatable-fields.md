# 0003. Drop request fields Converse cannot carry

- Status: Accepted
- Date: 2026-06-12 (fields added since are listed with their PRs)

## Context

Claude Code sends Anthropic-only fields. Forwarding one that Converse rejects fails the whole request; there is no partial acceptance.

## Decision

Drop, at translation time:

- `stop_sequences`: every non-Anthropic model probed (8 of 8 on 2026-06-12) rejects `stopSequences` on Converse with a ValidationException.
- Anthropic-hosted tools (`web_search_*`, `computer_*`, `bash_*`, `text_editor_*`): they run on Anthropic's servers; Bedrock has no counterpart.
- `output_config.format`, `context_management`, `metadata.user_id`, the `thinking` request parameter, `top_k`: no Converse equivalent.
- `cache_control`: Converse expresses caching with `cachePoint` blocks; see [0009](./0009-implicit-caching-only.md).

Map instead of drop where a measured equivalent exists: `output_config.effort` becomes `additionalModelRequestFields.reasoning_effort` for the models in [0004](./0004-sourced-per-model-tables.md)'s effort table (#9).

## Consequences

The client gets a working response without those features. The full list and the empty-content rules are in [architecture.md](../architecture.md#translation-responsibilities).
