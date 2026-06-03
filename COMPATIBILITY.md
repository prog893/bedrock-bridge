# bedrock-bridge: Bedrock model compatibility matrix

Measured end-to-end: `bedrock-bridge --model <id> --claude --print ...` drives a real Claude Code session against the bridge for each model. Two turns per model:

- **text+tool**: prompt forces a Bash tool call (`echo MATRIX_OK_*`).
- **image+tool**: Claude Code `Read`s a PNG from disk. The image ends up inside a `tool_result`, which exercises the hoist-image-out-of-toolResult transform.

Region: `ap-northeast-1`. bedrock-bridge serves only non-Claude models; Anthropic IDs are refused at preflight (use Claude Code's native `CLAUDE_CODE_USE_BEDROCK=1` mode for Claude).

## Matrix

| Model | text+tool | image+tool | notes |
|-------|-----------|------------|-------|
| `moonshotai.kimi-k2.5` | OK | OK | vision model; image hoist works |
| `moonshot.kimi-k2-thinking` | OK | N/A | no vision modality |
| `minimax.minimax-m2.5` | OK | N/A | no vision modality |
| `deepseek.v3.2` | OK | N/A | no vision modality |
| `qwen.qwen3-235b-a22b-2507-v1:0` | OK | OK | vision model |
| `qwen.qwen3-coder-480b-a35b-v1:0` | OK | N/A | no vision modality |
| `qwen.qwen3-vl-235b-a22b` | OK | OK | vision model |
| `zai.glm-4.7` | OK | N/A | no vision modality |
| `zai.glm-5` | OK | N/A | no vision modality |
| `mistral.mistral-large-3-675b-instruct` | OK | OK | vision model |

## Reading the results

- **`text+tool` passes on every model.** Tool-use translation and tool-name/ID shortening are safe across providers.
- **`image+tool` is `N/A` for text-only models.** The bridge detects the missing IMAGE input modality at preflight and replaces image content with an explicit text marker before the request reaches Bedrock, so the model answers honestly instead of confabulating. Use a vision-capable model for image work.

If you hit a failure with a model that should work, it is most likely a bridge-side translation gap (request/response shaping, streaming, tool or image handling), not a Bedrock or model-provider problem. These gaps are work in progress; please file an issue with the model ID and the bridge log. Treat a failure here as "the bridge does not handle this model's shape yet" rather than "Bedrock or the model is broken."

## Reproducing

```bash
./.venv/bin/python scripts/matrix_e2e.py
# or a subset
./.venv/bin/python scripts/matrix_e2e.py --only kimi qwen
```

The script writes `/tmp/bridge_matrix.md` and leaves per-run bridge logs in `/tmp/bedrock-bridge-<port>.log` for inspection.
