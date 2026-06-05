# Architecture

How `bedrock-bridge` translates Anthropic Messages API traffic into Amazon Bedrock Converse API calls, and the design choices behind each piece.

## Components

```
bedrock_bridge/
├── cli.py        # CLI: env+flag config, preflight, --claude gating
├── server.py     # FastAPI proxy: /v1/messages, /set-model, /health
└── translate.py  # Anthropic <-> Bedrock Converse translation
```

There is no shared state across processes. Each `bedrock-bridge` invocation starts a uvicorn subprocess on a random free port. Multiple sessions run in parallel without coordination.

## Process layout

```
bedrock-bridge (CLI)
    |
    |-- spawn: uvicorn server (random port)
    |
    |-- POST /set-model { main_id, light_id }
    |
    |-- (with --claude) spawn: claude
    |       env: ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, ANTHROPIC_DEFAULT_HAIKU_MODEL, ANTHROPIC_API_KEY
    |
    \-- (without --claude) hold; print env wiring; wait on Ctrl-C
```

The CLI process owns three children: the proxy server (always), and the `claude` CLI (only when `--claude` is passed). Cleanup is signal-driven; SIGINT terminates the proxy.

## Request lifecycle

A single Anthropic-API request flows like this:

1. Client calls `POST http://127.0.0.1:<port>/v1/messages` with an Anthropic JSON body containing `model`, `messages`, `system`, `tools`, `max_tokens`, `stream`, etc.
2. `server._route(model_id)` picks the Bedrock target by exact match against the configured main and light IDs.
3. `translate.anthropic_to_converse(body)` converts the Anthropic body into Bedrock Converse `kwargs` and a small metadata dict (used during the response leg).
4. `boto3 bedrock-runtime client.converse(...)` or `.converse_stream(...)` is called against the routed model ID.
5. `translate.converse_to_anthropic(...)` (non-streaming) or `translate.converse_stream_to_anthropic_events(...)` (streaming) converts the Bedrock response back to Anthropic shape.
6. The proxy returns either a JSON body or an SSE stream of Anthropic events.

## Routing

When the CLI launches Claude Code under `--claude`, it sets two env vars on the spawned process:

- `ANTHROPIC_MODEL=<main_id>` fills the primary slot.
- `ANTHROPIC_DEFAULT_HAIKU_MODEL=<light_id>` fills the light slot used by Claude Code's background tasks (auto-mode safety classifier, session title generation, summarization). Only set if a light model is configured.

Claude Code emits those exact strings in outgoing `model` fields. The proxy keys on exact match:

```python
def _route(model_alias: str) -> str:
    if _light_model and model_alias == _light_model:
        return _light_model
    if _light_model and "haiku" in model_alias.lower():  # safety net for clients we don't control
        return _light_model
    if _main_model:
        return _main_model
    return model_alias
```

The substring fallback covers Anthropic-API clients that emit native Anthropic model names (e.g. `claude-haiku-4-5`) without going through our env wiring.

## Translation responsibilities

`translate.py` is where the bulk of the work lives. The non-obvious behaviors:

- **Tool name and use-ID shortening.** Bedrock Converse rejects tool names or `toolUseId` values longer than 64 characters. Claude Code emits MCP tool names like `mcp__aws-billing-cost-management__list-cost-allocation-tag-backfill-history` that exceed this. We shorten to `prefix[:55] + "_" + sha256[:8]` and keep a bidirectional in-memory map so the matching `toolResult` block references the same shortened ID, then restore the original on the way back.
- **Image blocks.** Anthropic sends `{source.type: "base64", data: "<str>"}`; Bedrock wants raw `bytes`. We `base64.b64decode` and normalize `image/jpg` to `jpeg` (Bedrock rejects `jpg`).
- **Image hoisting from `tool_result`.** Some Bedrock models reject images nested inside `toolResult.content`. We hoist any image blocks out of tool-result content into a sibling user-message position before sending. Vision-capable models still see the image; for text-only models the image is adapted before send (see "Vision adaptation" below).
- **`stop_sequences` is dropped.** Every non-Anthropic Bedrock model rejects `stopSequences` with `ValidationException: This model doesn't support the stopSequences field`. The bridge does not serve Anthropic targets (preflight refuses them; see "Refusal" below), so the field is dropped unconditionally.
- **Server-side Anthropic tools are dropped.** Anthropic's hosted tools (`web_search_*`, `computer_*`, `bash_*`, `text_editor_*`) execute on Anthropic's servers and have no Bedrock equivalent. We strip them from the `tools` list. If that leaves the list empty, `toolConfig` is omitted (Bedrock rejects an empty tool list).
- **Streaming.** Bedrock `converse_stream` produces a different event shape than Anthropic SSE. `converse_stream_to_anthropic_events` translates each Converse stream chunk into the matching Anthropic events (`message_start`, `content_block_*`, `message_delta`, etc.) and the proxy emits them as SSE.
- **Thinking / reasoning blocks.** Models like Kimi K2 Thinking and Anthropic's extended-thinking models emit reasoning content in `output.message.content[*].reasoningContent`. We translate those to Anthropic `thinking` blocks in the response.

## Vision adaptation

A text-only main model cannot accept image input. `server.messages` detects this (the routed model's IMAGE modality flag, set at preflight) and adapts the body before send. There are two paths:

- **No `--vision-model` configured.** `_strip_images_from_body` replaces each image block with a text marker telling the model to inform the user that images need a vision model and how to enable one. The turn is forwarded so the session continues.
- **`--vision-model` configured.** `_stash_images_for_describe` replaces each image with a `describe_image` marker carrying a content-derived handle (`img-` + sha256 prefix, not a sequential index), and stashes the real Bedrock image block in a per-request `handle -> block` map. A `describe_image` toolSpec is injected into the main model's `toolConfig`; this tool is never exposed to Claude Code. `_run_describe_loop` then drives the main model non-streaming: when it calls `describe_image`, the bridge runs the vision model (`_call_vision_model`) on the stashed bytes with the model's `prompt`, returns the description as a `toolResult` framed as a second-hand text rendering (`_describe_result_text`), and re-invokes. Any non-`describe_image` tool call in the same assistant turn is discarded; the model re-decides with the descriptions now in context. The loop ends on the first turn with no `describe_image` call (capped at `_MAX_DESCRIBE_ROUNDS`).

Because the describe loop must inspect each assistant turn before deciding to continue, it runs non-streaming even when the client asked to stream. `_buffered_message_to_sse` replays the final buffered message as the Anthropic SSE event sequence so a streaming client still gets a stream. The common no-image path streams directly from Bedrock.

If the main model is itself image-capable but `--vision-model` is set, preflight treats main as text-only (with a warning) so images route to the vision model.

## Startup output

```
  Main:   moonshotai.kimi-k2.5
  Light:  minimax.minimax-m2.5
  Proxy:  http://127.0.0.1:54321

  Preflight:
    ✓ identity: 123456789012 / alice
    ✓ region: ap-northeast-1
    ✓ main: moonshotai.kimi-k2.5
    ✓ light: minimax.minimax-m2.5

  Logs:   /tmp/bedrock-bridge-54321.log
  Starting proxy... OK
```

If `--claude` is not passed, the bridge then prints the env vars to wire any Anthropic-API client to the proxy and waits on Ctrl-C. With `--claude`, it spawns the `claude` CLI with `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, and `ANTHROPIC_DEFAULT_HAIKU_MODEL` set.

## Preflight

Before serving any traffic, the CLI runs three checks against AWS and fails fast if any fail:

1. **Identity.** `sts:GetCallerIdentity` once. Prints `<account>/<principal>`. Catches missing credentials, expired SSO sessions, and wrong-account misconfigurations.
2. **Region.** Resolved via boto3's standard chain (CLI flag, then `AWS_REGION` / `AWS_DEFAULT_REGION`, then the active profile). If nothing resolves, fail with a pointer to the env vars.
3. **Per-model access.** For each configured model ID, call `bedrock:GetFoundationModel` (foundation IDs) or `bedrock:GetInferenceProfile` (inference-profile IDs starting with `global.`, `us.`, `eu.`, `apac.`, etc). Surfaces both IAM denials and "model access not enabled in console" errors with the verbatim AWS message.

Preflight exists because the user-visible failure mode of skipping it is opaque: Claude Code starts, sends a request, gets a 500 from the proxy with a nested AWS error string mid-conversation. Preflight surfaces the error before any traffic flows.

## Refusal of Anthropic IDs

If the configured main or light model is an Anthropic ID (`anthropic.*`, `global.anthropic.*`, etc.), the CLI refuses to start and prints the env vars to use Claude Code's native Bedrock mode instead:

```
export CLAUDE_CODE_USE_BEDROCK=1
export ANTHROPIC_MODEL=<id>
claude
```

Reasoning: Claude Code already speaks Bedrock natively for Anthropic models. Routing through the bridge adds a hop, breaks features the bridge intentionally drops (`stopSequences`, extended-thinking flags), and inverts the bridge's value proposition.

## Privacy defaults

When Claude Code is spawned with `--claude`, the bridge treats Claude Code as if it were on the Anthropic API (because `ANTHROPIC_BASE_URL` points at us). That would normally turn on telemetry, Sentry, `/feedback`, autoupdater, and surveys. To match the privacy posture of a native `CLAUDE_CODE_USE_BEDROCK=1` session, the bridge sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` on the spawned process.

The umbrella variable is documented as equivalent to setting `DISABLE_AUTOUPDATER`, `DISABLE_FEEDBACK_COMMAND`, `DISABLE_ERROR_REPORTING`, and `DISABLE_TELEMETRY` together; it also gates session quality surveys. Local state (transcripts under `~/.claude/projects/`, `/cost`, auto-memory) is unaffected.

If a user already exports `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` themselves, the bridge respects it (including a `0` override that re-enables traffic). The bridge does not touch `DO_NOT_TRACK` or other related variables.

The WebFetch domain safety check is not affected by the umbrella variable. Disabling it requires a `skipWebFetchPreflight: true` entry in the user's settings file, which the bridge does not modify.

## CloudTrail attribution

The boto3 client is configured with `user_agent="bedrock-bridge/<version>"` and matching `user_agent_extra`. CloudTrail events for `Converse` and `ConverseStream` show this UA, making bridge traffic identifiable in logs alongside the real `modelId`.

## Per-instance proxy

Each invocation picks a random free port via `find_free_port()` and spawns its own uvicorn subprocess. Uvicorn stdout/stderr is redirected to `/tmp/bedrock-bridge-<port>.log` so harmless SSE disconnect warnings don't clobber Claude Code's TUI. Two parallel `bedrock-bridge` invocations work without any coordination.

## What's intentionally not here

- **No config files.** All configuration is env vars or CLI flags.
- **No persistence.** Tool name and use-ID maps are in-memory and per-proxy. Sessions are independent.
- **No retry logic at the bridge layer.** AWS errors surface verbatim; the client (Claude Code) handles its own retries.
- **No rate limiting or quota enforcement.** That's Bedrock's job.
- **No model alias registry.** Pass fully-qualified Bedrock IDs only. Anthropic foundation IDs (`anthropic.*`) are auto-prefixed with `global.` since Bedrock requires the inference-profile form.
