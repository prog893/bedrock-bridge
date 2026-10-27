# Working on bedrock-bridge

Instructions for coding agents and contributors. User-facing docs are in
[README.md](./README.md) and [docs/](./docs/); decisions and their reasons are
in [docs/adr/](./docs/adr/); review, test and writing rules are in
[CONTRIBUTING.md](./CONTRIBUTING.md); releases in
[docs/releasing.md](./docs/releasing.md).

Read CONTRIBUTING.md before changing anything: @CONTRIBUTING.md

## Public repo, private notes

This repository is public. Its history, issues and PRs must never contain:

- AWS account IDs or IAM principal names
- hostnames, usernames, home-directory or temp-directory paths, IP addresses
  (loopback is fine; mask any other)
- names or details of company-internal tools
- content of leaked or decompiled Claude Code source, or strings extracted from
  its binary
- raw traffic captures, session or device identifiers, session content

Maintainers keep notes like these outside the repo, in a workspace directory
that contains the clone. Never copy them into the repo, and never commit a
notes, journal or todo file. Claude Code behavior may be described when it was
observed (its debug log, wire traffic, a test run) or is in its public docs.

## Layout

```
bedrock_bridge/
  __init__.py         __version__ (read by pyproject, --version, the boto3 User-Agent)
  cli.py              preflight, model slots, spawns the server and claude
  server.py           Starlette app, routing, error mapping
  translate.py        Anthropic Messages <-> Converse
  context_windows.py  context window per model, from the AWS model cards
docs/                 architecture, error mapping, logging, IAM, compatibility, ADRs
scripts/              e2e grader, dev probes, git hooks
tests/                offline tests, functional/ (real Bedrock), manual/ probes
```

## Run-time invariants

- The bridge serves the Anthropic Messages API on `/v1/messages` and calls
  bedrock-runtime Converse / ConverseStream only
  ([ADR 0001](./docs/adr/0001-converse-only.md)).
- Two model slots: main (`--model` / `BEDROCK_BRIDGE_MODEL`, required) and
  light (`--model-light` / `BEDROCK_BRIDGE_MODEL_LIGHT`, optional). Routing is
  an exact-string match in `server._route` against the IDs the CLI set on
  Claude Code's process (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`).
  Any other name containing "haiku" goes to the light model when one is set;
  everything else, such as the auto-mode classifier's model name, goes to main.
- Anthropic model IDs are refused at preflight
  ([ADR 0002](./docs/adr/0002-no-claude-models.md)).
- Under `--claude` the CLI sets these on the spawned `claude`, each overridable
  by a value the user already exported:
  - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`: telemetry, error reporting,
    feedback, autoupdater and surveys off.
  - `CLAUDE_CODE_AUTO_MODE_SERVER=0`: auto mode uses Claude Code's local
    classifier; a server-side verdict never arrives through Converse.
  - `CLAUDE_CODE_MAX_CONTEXT_TOKENS`: the main model's window from
    `context_windows.py`; Claude Code otherwise assumes 200K for every bridged
    model ([ADR 0004](./docs/adr/0004-sourced-per-model-tables.md)).
- `--claude` is a hard argv boundary: every token after it goes to `claude`
  verbatim, so bridge flags such as `--log-level` must come before it.
- Log tiers: default, verbose, debug. The debug tier writes prompt content
  (PII) to the log file; the CLI asks for interactive consent and refuses on a
  non-TTY. Image bytes are redacted (`server._scrub_bytes_only`); text is
  verbatim. See [docs/logging.md](./docs/logging.md).
- Fields Converse cannot carry are dropped; effort is mapped for the models in
  `translate._EFFORT_BY_MODEL`
  ([ADR 0003](./docs/adr/0003-drop-untranslatable-fields.md)).

## Translation details (translate.py)

- Tool names and tool-use IDs over Bedrock's 64-character cap (or with
  characters it rejects) become `prefix[:55] + "_" + sha256[:8]`, with a
  bidirectional map; a `tool_use` and its `tool_result` resolve to the same
  value.
- Response-side tool_use IDs are minted (`toolu_bridge_<hex>`)
  ([ADR 0006](./docs/adr/0006-mint-tool-use-ids.md)).
- Images: base64 becomes raw bytes; `image/jpg` becomes `jpeg`. Images nested
  in `tool_result` are hoisted into a sibling user content block, since some
  models reject them there.
- System-role entries in `messages` are folded into the adjacent user turn
  ([ADR 0005](./docs/adr/0005-fold-system-messages.md)).
- Streaming: some models (kimi-k2-thinking and similar) send no
  `contentBlockStart` for text or reasoning. The bridge synthesizes the
  Anthropic `content_block_start` on the first delta of an unseen index, typed
  from the delta (`reasoningContent` to thinking, `text` to text, `toolUse` to
  tool_use). Without it, Claude Code renders reasoning as assistant text.
- The first text or thinking delta of each block loses exactly one leading
  space: some models' chat templates prefix turns with one.
- `signature_delta` is emitted when Bedrock includes signatures in
  `reasoningContent` deltas.

## Error mapping (server.py `_format_error`)

Bedrock errors that Claude Code can recover from are rewritten into wording it
acts on; everything else becomes a 500 with a `[bedrock-bridge]` prefix and
the raw Bedrock text ([ADR 0007](./docs/adr/0007-error-mapping.md)). A
body-buffer overflow is reported as "prompt is too long" with the body size in
bytes standing in for tokens: only the gap's magnitude matters, and a large gap
makes compaction drop enough. The catalog and verbatim samples are in
[docs/error-mapping.md](./docs/error-mapping.md); add a sample and an offline
test for every new error shape.

## Preflight (cli.py)

1. `sts:GetCallerIdentity` once.
2. The region must resolve through boto3's chain; otherwise fail with an
   env-var hint.
3. For each configured model: an ID with an inference-profile prefix
   (`global.`, `us.`, `eu.`, `apac.`, `apne1.`, `apne2.`, `apne3.`) is
   checked with `bedrock:GetInferenceProfile`, any other with
   `bedrock:GetFoundationModel`.
4. AWS errors are printed verbatim and the CLI exits 1. No traffic flows until
   every check passes.

## Tests

Three layers, described in [CONTRIBUTING.md](./CONTRIBUTING.md#tests):

- Offline (`pytest -m 'not functional'`): the regression register. Inputs are
  hand-built minimal payloads, never captured sessions. Every fixed Bedrock
  field failure gets a case.
- Functional (`pytest -m functional`): real Bedrock through a spawned bridge.
  It fails, without skipping, when AWS is unreachable; that is deliberate.
- E2E grader (`scripts/e2e_grade.py`): a model describes
  `tests/fixtures/sample_01.jpg` through the bridge (copied to a random temp
  path so the file name gives no hint) and `claude -p` grades it against
  `sample_01.annotation.md`. The judge must not route through the bridge.

The pre-commit hook (`git config core.hooksPath scripts/git-hooks`) runs the
offline and functional layers.

## Dev probes

- `tests/manual/compat_matrix.py`: direct Converse probes per model; fastest
  check of whether a model accepts the bridge's request shapes.
- `tests/manual/matrix_e2e.py`: bridge plus Claude Code per model, classified
  from the bridge log.
- `scripts/probe_tool_use.py`: raw Converse for one model, to inspect how it
  emits `toolUse`. Use it when adding a provider.

Ad-hoc probes stay out of the repo; their results go into the issue or PR they
support.

## Also not done

Beyond the ADRs: no config files, no persistence, no retries at the bridge
layer, no rate limiting, and no model alias registry (pass fully-qualified
Bedrock IDs). See
[architecture.md](./docs/architecture.md#whats-intentionally-not-here).
