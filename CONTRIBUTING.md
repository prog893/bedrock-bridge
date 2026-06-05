# Contributing

## Prerequisites

- [uv](https://docs.astral.sh/uv/) for the venv and installs.
- AWS credentials and region (profile, env vars, or SSO) with access to the
  Bedrock models you test against. Required for the functional suite.
- The `claude` CLI (`brew install claude-code`) for the e2e grader, configured
  with a Claude path that does not route through this bridge (see Tests).

The `[dev]` extra installs the only Python dev dependency, pytest.

## Local setup

```bash
git clone https://github.com/prog893/bedrock-bridge.git
cd bedrock-bridge && uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'        # [dev] pulls in pytest
pytest                            # run the suite
git config core.hooksPath scripts/git-hooks   # run tests on every commit
```

The `[dev]` extra adds pytest; runtime installs (including the Homebrew
formula) never pull it in.

## Tests

- `pytest -m 'not functional'`: offline unit tests, no network. One case per
  past Bedrock-shape rejection; add one here when you fix a new field failure.
- `pytest -m functional`: spawns the bridge against real Bedrock with
  hand-built payloads and asserts on the response envelope. Needs AWS
  credentials and runs on the pre-commit hook. Defaults to minimax-m2.5
  (text) and kimi-k2.5 (image); override with `BEDROCK_BRIDGE_TEST_TEXT_MODEL`
  and `BEDROCK_BRIDGE_TEST_IMAGE_MODEL`.
- `scripts/e2e_grade.py --model <id>`: drives a model through the bridge to
  describe a known image, then scores the output against a ground-truth
  annotation using `claude -p` as judge. Not part of pytest (costs tokens,
  needs Claude Code).

The grader's judge needs a Claude path that does not go through this bridge (a
first-party Anthropic key, or native `CLAUDE_CODE_USE_BEDROCK=1`). The bridge
refuses Anthropic model IDs at preflight, and grading the bridge with a judge
that runs on the bridge is circular.

## Pull requests

Fill in the test-plan checklist in the PR template: run the offline and
functional suites and the e2e grader against your diff, and record the models
and scores. Don't check boxes you didn't run.

`scripts/` also contains dev-only probes; see [scripts/README.md](./scripts/README.md).
