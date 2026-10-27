# 0001. Converse is the only inference API

- Status: Accepted; API selection is revisited in #14
- Date: 2026-06-03 (initial commit; probed 2026-06-12)

## Context

The bridge accepts the Anthropic Messages API and must reach non-Claude Bedrock models. Bedrock offers three paths: Converse / ConverseStream on bedrock-runtime, InvokeModel with each provider's native body, and bedrock-mantle. Per the AWS docs, Mantle serves the Anthropic Messages API only for Claude models; other models on Mantle expose Chat Completions. InvokeModel bodies and responses differ per provider (for example, Kimi on InvokeModel takes an OpenAI-style body and honors `stop`).

## Decision

Translate to Converse and ConverseStream only.

## Consequences

- One request and response shape for every provider; no per-provider body code.
- Fields Converse cannot carry are dropped (see [0003](./0003-drop-untranslatable-fields.md)). The clearest cost is `stop_sequences`, which InvokeModel would honor on some models but Claude Code sends rarely.
- Model features that exist only on Chat Completions or Responses (for example Kimi K3's effort control and explicit prompt caching) are out of reach until #14.
