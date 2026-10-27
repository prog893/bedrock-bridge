# 0007. Map Bedrock errors to messages Claude Code recovers from

- Status: Accepted
- Date: 2026-06-04

## Context

Claude Code recovers from some API errors by matching their text: a "prompt is too long" error triggers compaction, an oversized-image error strips the image. Bedrock words these failures differently, so passed through unchanged they land in Claude Code's unknown-error path, and it resends the same oversized request.

## Decision

Rewrite the Bedrock errors that have a recovery path into the wording Claude Code acts on, keep the raw Bedrock text in the message, and prefix everything else with `[bedrock-bridge]` so the user can tell the error passed through the bridge. A body-buffer overflow is reported as "prompt is too long" with a token gap derived from the body size, so compaction removes enough.

## Consequences

The catalog of matched errors, their rewrites and verbatim samples is in [error-mapping.md](../error-mapping.md). New error shapes need a sample there and an offline test.
