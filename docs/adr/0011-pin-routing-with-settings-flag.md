# 0011. Pin routing with `--settings` under `--claude`

- Status: Accepted
- Date: 2026-10-28 (#27)

## Context

An `env` block in a Claude Code settings file overrides the same variable in the process environment ([settings reference](https://code.claude.com/docs/en/settings-reference.md#env)). A user who also runs Claude Code natively on Bedrock may keep `CLAUDE_CODE_USE_BEDROCK`, `ANTHROPIC_BASE_URL` or Anthropic model IDs in `~/.claude/settings.json`, and a cloned repo can ship them in `.claude/settings.json`. Under `--claude` such a block sends the session around the bridge, or puts an Anthropic ID on a model slot, even though the CLI sets the bridge's values on the spawned process.

Measured on Claude Code 2.1.293 against a local stub server: user, project and local settings `env` each overrode the process value of `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` and `ANTHROPIC_BASE_URL`; a `--settings` value overrode all three files; an empty string in `--settings` behaved as unset; with two `--settings` flags the last one replaced the first.

`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` ([env vars](https://code.claude.com/docs/en/env-vars.md)) also blocks settings files from changing provider, endpoint and auth variables. It is documented for host platforms that embed Claude Code, changes telemetry and auto-mode defaults, and drops other settings-sourced variables such as `NODE_EXTRA_CA_CERTS`. That is more than the bridge needs.

## Decision

Under `--claude`, pass `--settings '{"env": {...}}'` to `claude` before the user's arguments, carrying `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL`, and setting `CLAUDE_CODE_USE_BEDROCK`, `_MANTLE`, `_VERTEX`, `_FOUNDRY`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_SMALL_FAST_MODEL` to `""`. The same values stay in the process environment. Ollama's proposed fix for the same problem takes this approach ([ollama/ollama#17991](https://github.com/ollama/ollama/pull/17991)).

## Consequences

- User, project and local settings can no longer redirect a bridged session or change its model slots. Managed settings still can; they rank above `--settings`.
- A `--settings` the user passes after `--claude` replaces the bridge's, so that user's settings files apply again. The CLI leaves it in place and prints a warning. `--model` after `--claude` still sets the session's model; the bridge routes it like any other name (the light model for its ID or, when one is set, any name containing "haiku"; the main model otherwise).
- Settings keys other than these `env` entries keep their file-based values.
