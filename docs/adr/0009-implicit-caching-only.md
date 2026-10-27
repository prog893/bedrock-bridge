# 0009. Implicit prompt caching only by default

- Status: Accepted; opt-in explicit caching is tracked in #22
- Date: 2026-10-27

## Context

Claude Code marks cache breakpoints with `cache_control`. Converse uses `cachePoint` blocks instead. Measured on Converse (2026-10-15): GLM 5.3 and Kimi K3 cache implicitly; only GLM 5.3 also accepts `cachePoint`; Kimi K3, Kimi K2.5, MiniMax M2.5 and gpt-oss reject it, in two different error shapes; every model tested rejects a `ttl` on the checkpoint. Bedrock reports cache reads and writes in usage, and the bridge passes them through, so Claude Code's own prompt-cache statistics work.

## Decision

Drop `cache_control` and rely on Bedrock's implicit caching. Keep the request prefix stable across requests ([0005](./0005-fold-system-messages.md)). Explicit caching, if built, is opt-in and never sends `ttl` (#22).

## Consequences

GLM 5.3's implicit hit rate varies on Bedrock's side; an opt-in `cachePoint` path would make it reliable for that model only.
