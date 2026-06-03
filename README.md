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

# Two-model setup: main + light
bedrock-bridge -m moonshotai.kimi-k2.5 --model-light minimax.minimax-m2.5 --claude

# Just run the proxy; wire your own client
bedrock-bridge --model moonshotai.kimi-k2.5
```

| Slot | Env var | CLI flag |
|------|---------|----------|
| Main (required) | `BEDROCK_BRIDGE_MODEL` | `--model` / `-m` |
| Light (optional) | `BEDROCK_BRIDGE_MODEL_LIGHT` | `--model-light` |

The light slot is for background tasks Claude Code dispatches to a smaller model. If no light model is configured, all requests route to the main model.

Claude Code's auto-mode safety classifier works through the bridge. With a light slot configured it runs there; without one it falls through to the main model.

Pass any Bedrock foundation ID (`moonshotai.kimi-k2.5`) or inference-profile ID (`us.meta.llama4-...`) directly. CLI flags override env vars.

Extra `claude` flags pass through after `--`: `bedrock-bridge -m moonshotai.kimi-k2.5 --claude -- --verbose`.

### Resuming sessions

Claude Code's `--continue` and `--resume` work normally through the bridge:

```bash
# Continue the most recent session in the current directory
bedrock-bridge -m moonshotai.kimi-k2.5 --claude -- --continue

# Pick a session interactively
bedrock-bridge -m moonshotai.kimi-k2.5 --claude -- --resume

# Resume a specific session by id
bedrock-bridge -m moonshotai.kimi-k2.5 --claude -- --resume <session-id>
```

### Aliases

Alias the bridge to a short command for frequent use. Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Dedicated command per model; leaves `claude` untouched
alias claude-kimi='bedrock-bridge -m moonshotai.kimi-k2.5 --model-light minimax.minimax-m2.5 --claude --'
alias claude-glm='bedrock-bridge -m zai.glm-5 --model-light zai.glm-4.7-flash --claude --'  # text-only; image turns intercepted

# Or override `claude` so every invocation routes through the bridge
alias claude='bedrock-bridge -m moonshotai.kimi-k2.5 --model-light minimax.minimax-m2.5 --claude --'
```

All forms accept the full `claude` flag set, including `--continue` and `--resume`.

## Privacy

Under `--claude`, the bridge sets `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` on the spawned Claude Code process. That umbrella opt-out disables Anthropic operational telemetry, Sentry error reporting, the `/feedback` command, the autoupdater, and session quality surveys. Local state (session transcripts, `/cost`, auto-memory) is unaffected. Override by exporting `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=0` before launch.

The bridge itself makes no outbound calls except to AWS Bedrock and STS, tagged with `User-Agent: bedrock-bridge/<version>`.

## Running Claude on Bedrock

bedrock-bridge does not serve Claude models. Use Claude Code's native Bedrock mode (`CLAUDE_CODE_USE_BEDROCK=1`); see Anthropic's [setup guide](https://code.claude.com/docs/en/amazon-bedrock).

## Known limitations

- macOS only.
- Bedrock models have a request body size cap, limiting the amount of data sendable in one request. When the cap is hit, Claude Code's TUI shows "Context limit reached · /compact or /clear to continue" and the session pauses. Run `/compact` to summarize old turns and continue, or `/clear` to start fresh. Common trigger: many large tool_result blocks (parallel screenshots, big file reads) accumulated across turns.
- On non-vision models, the bridge replaces image blocks with an explicit text marker before forwarding to Bedrock so the request still validates and the model gets a clear "image cannot be shown" signal. The model is instructed to tell the user images are not supported. Use a vision-capable main model when working with images.
- Claude Code's `/model` command is not supported. Every request routes to the model configured at bridge startup; in-session model swaps have no effect. Restart the bridge with a different `--model` to switch.

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
