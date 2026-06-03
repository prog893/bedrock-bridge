# bedrock-bridge

Run Claude Code (and any Anthropic-API client) against any non-Claude Bedrock model: Kimi, Llama, DeepSeek, Qwen, GLM, MiniMax, Mistral. Local proxy that translates the Anthropic Messages API to the Bedrock Converse API.

## Install

```bash
brew tap prog893/tap
brew install bedrock-bridge
```

Prerequisites: macOS, AWS credentials, Bedrock model access enabled, IAM permissions ([IAM.md](./IAM.md)). For `--claude`: `claude` CLI on PATH (`brew install claude-code`).

## Quickstart

```bash
# Run Claude Code through Kimi K2.5
bedrock-bridge --model moonshotai.kimi-k2.5 --claude

# Two-model setup: main + small/fast
bedrock-bridge -m moonshotai.kimi-k2.5 --model-light minimax.minimax-m2.5 --claude

# Just run the proxy; wire your own client
bedrock-bridge --model moonshotai.kimi-k2.5
```

| Slot | Env var | CLI flag |
|------|---------|----------|
| Main (required) | `BEDROCK_BRIDGE_MODEL` | `--model` / `-m` |
| Small/fast (optional) | `BEDROCK_BRIDGE_MODEL_LIGHT` | `--model-light` |

The small/fast slot is for background tasks Claude Code dispatches to a smaller model. Skip it and everything routes to main.

Pass any Bedrock foundation ID (`moonshotai.kimi-k2.5`) or inference-profile ID (`us.meta.llama4-...`) directly. CLI flags override env vars.

Extra `claude` flags pass through after `--`: `bedrock-bridge -m kimi-k2.5 --claude -- --verbose`.

## Privacy

Under `--claude`, the bridge sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` on the spawned Claude Code process. That umbrella opt-out disables Anthropic operational telemetry, Sentry error reporting, the `/feedback` command, the autoupdater, and session quality surveys. Local state (session transcripts, `/cost`, auto-memory) is unaffected. Override by exporting `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=0` before launch.

The bridge itself makes no outbound calls except to AWS Bedrock and STS, tagged with `User-Agent: bedrock-bridge/<version>`.

## Running Claude on Bedrock

bedrock-bridge does not serve Claude models. Use Claude Code's native Bedrock mode (`CLAUDE_CODE_USE_BEDROCK=1`); see Anthropic's [setup guide](https://code.claude.com/docs/en/amazon-bedrock).

## Docs

- [ARCHITECTURE.md](./ARCHITECTURE.md): request flow, translation, preflight, routing.
- [IAM.md](./IAM.md): minimum policy template.
- [COMPATIBILITY.md](./COMPATIBILITY.md): end-to-end matrix across providers.

## Development

```bash
git clone https://github.com/prog893/bedrock-bridge.git
cd bedrock-bridge && uv venv && source .venv/bin/activate
uv pip install -e .
```

`scripts/` contains dev-only probes ([scripts/README.md](./scripts/README.md)).

## License

MIT. See [LICENSE](./LICENSE).
