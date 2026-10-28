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
git config core.hooksPath scripts/git-hooks   # ruff fix and format on every commit
```

The `[dev]` extra adds pytest; runtime installs never pull it in.

## Tests

CI runs the offline suite, `ruff check` and `ruff format --check` on every pull
request. The pre-commit hook runs ruff only: it applies fixes and formatting to
the staged files and stops the commit when anything changed, so you can review
and stage the result.

- `pytest -m 'not functional'`: offline unit tests, no network. One case per
  past Bedrock-shape rejection; add one here when you fix a new field failure.
- `pytest -m functional`: spawns the bridge against real Bedrock with
  hand-built payloads and asserts on the response envelope. Needs AWS
  credentials; run it by hand before opening a PR. Defaults to minimax-m2.5
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

PRs are merged (squash, branch deleted) once the CodeRabbit review approves the
head commit. Fix valid findings that are in scope; for the rest, reply on the
thread with the reason and open an issue if the work is worth tracking.
CodeRabbit's free tier rate-limits reviews; re-request with
`@coderabbitai review` after the window passes. No `Co-authored-by` trailers.

Releases are cut by the maintainer on request; see
[docs/releasing.md](./docs/releasing.md).

## Where things go

- Bugs and deferred work: GitHub issues, with the measurements that support
  them.
- Fixes: PRs that reference their issue.
- Design decisions and their reasons: an ADR in [docs/adr/](./docs/adr/).
- How the bridge works today: the docs in [docs/](./docs/). Docs describe the
  current behavior; comparisons with an API the bridge does not use belong in
  the PR that adds that API.
- No journals, session logs or todo lists in the repo.

Nothing private goes into the repo, issues or PRs: no hostnames, IP
addresses, usernames, home-directory paths, AWS account IDs, IAM principals,
or session content. Describe Claude Code behavior from its public docs or from
observed traffic.

## Writing style

Applies to code comments, docs, commit messages, issues and PRs.

- No em dashes or en dashes. Use a period, semicolon, comma, colon or
  parentheses.
- No "X, not Y" constructions. State the point directly.
- No marketing language.
