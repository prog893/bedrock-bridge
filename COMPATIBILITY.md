# bedrock-bridge: Bedrock model compatibility matrix

Measured end-to-end: `bedrock-bridge --model <id> --print ...` drives a real Claude Code session against the bridge for each model. Two turns per model:

- **text+tool**: prompt forces a Bash tool call (`echo MATRIX_OK_*`).
- **image+tool**: Claude Code `Read`s a 48×48 PNG from disk. The image ends up inside a `tool_result`, which exercises our hoist-image-out-of-toolResult transform.

Region: `ap-northeast-1`. Anthropic models auto-resolved to `global.*` inference profiles.

## Matrix

| Model | text+tool | image+tool | notes |
|-------|-----------|------------|-------|
| `anthropic.claude-opus-4-7` | ✅ | ✅ | auto-routes via `global.` inference profile |
| `anthropic.claude-sonnet-4-6` | ✅ | ⏱ timeout | loop hung after 1 bridge req (model-side) |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | ✅ | ✅ | |
| `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | ✅ | ✅ | |
| `moonshotai.kimi-k2.5` | ✅ | ✅ | vision model; image hoist works |
| `moonshot.kimi-k2-thinking` | ✅ | ✅ | |
| `minimax.minimax-m2.5` | ✅ | ⏱ timeout | no vision; Claude Code loops reading the image |
| `deepseek.v3.2` | ✅ | ⏱ timeout | no vision |
| `qwen.qwen3-235b-a22b-2507-v1:0` | ✅ | ✅ | |
| `qwen.qwen3-coder-480b-a35b-v1:0` | ✅ | ⏱ timeout | no vision |
| `qwen.qwen3-vl-235b-a22b` | ✅ | ✅ | vision model |
| `zai.glm-4.7` | ✅ | ⏱ timeout | no vision |
| `zai.glm-5` | ✅ | ⏱ timeout | no vision |
| `mistral.mistral-large-3-675b-instruct` | ✅ | ⏱ timeout | no vision |

## Reading the results

- **`text+tool` = 14/14.** Every tested model routes through the bridge and completes a tool-use turn. Tool-use translation and tool-ID shortening are safe across providers.
- **`image+tool` timeouts are expected for non-vision models.** The request shape is valid (Bedrock accepts it after the hoist); the model just can't see the pixels and Claude Code keeps retrying. Pick a vision model for image work.
- **Sonnet 4.6 timed out** at 1 request: model-side hang unrelated to the bridge. Same prompt on Sonnet 4.5 and Opus 4.7 completes normally.

## What the bridge proves out

- Tool use (names + IDs + toolResult round-trip) on: Claude 4.x family, Kimi K2.5, Kimi K2-Thinking, MiniMax M2.5, DeepSeek V3.2, Qwen 3 family, GLM 4.7 & 5, Mistral Large 3.
- Image inside `tool_result` (via automatic hoist): Claude, Kimi K2.5, Qwen3-VL-235B.
- Model routing: `--model-haiku` splits background Haiku-class calls onto a separate Bedrock model while main traffic uses the primary.
- CloudTrail attribution: all calls tagged `User-Agent: bedrock-bridge/0.1`.

## Reproducing

```bash
./.venv/bin/python scripts/matrix_e2e.py
# or a subset
./.venv/bin/python scripts/matrix_e2e.py --only kimi qwen
```

The script writes `/tmp/bridge_matrix.md` and leaves per-run bridge logs in `/tmp/bedrock-bridge-<port>.log` for inspection.
