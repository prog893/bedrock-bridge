# 0004. Per-model tables only when sourced

- Status: Accepted
- Date: 2026-10-27

## Context

The bridge started with no per-model state: every model got the same translation, and "hardcode a table per model" was listed as something not to do (for example a context-window table). Two cases changed that. Effort values are validated per model by Bedrock, so a single mapping fails on some models (#9, 2026-10-08). And Claude Code assumes a 200K context window for every model ID it does not recognize, which is every model the bridge serves; GLM 5.3 and Kimi K3 have 1M, gpt-oss has 128K (#21, 2026-10-27).

## Decision

A per-model table is allowed when each entry comes from a measurement or from the AWS model cards, and the source and date are recorded next to the table. Models missing from a table get the generic behavior.

- `translate._EFFORT_BY_MODEL`: effort values each model accepts, measured.
- `context_windows.CONTEXT_WINDOWS`: context windows from the AWS model cards, passed to Claude Code as `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

## Consequences

- Tables go stale as AWS adds or changes models; refresh them from the same source.
- Runtime detection is still not done: AWS exposes no context-window or effort API.
