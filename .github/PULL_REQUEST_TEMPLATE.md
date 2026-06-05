## Summary

<!-- What changed and why. -->

## Test plan

Required before marking ready for review. This applies to every author,
including AI agents (Claude Code) opening PRs.

- [ ] Offline tests pass: `pytest -m 'not functional'`
- [ ] Functional tests pass (real Bedrock through the bridge):
      `pytest -m functional` <!-- needs AWS creds; hits minimax + kimi -->
- [ ] E2E grader run against this diff, no errors, score above threshold:
      `python scripts/e2e_grade.py --model moonshotai.kimi-k2.5`
  - Model(s) tested:
  - Score(s):

### Why the grader cannot use this bridge

The e2e grader uses `claude -p` as an independent judge. That judge must reach
Claude through a path other than bedrock-bridge (a first-party Anthropic API
key, or native `CLAUDE_CODE_USE_BEDROCK=1`). Grading the bridge with a judge
that itself runs on the bridge is circular: a translation bug would corrupt
both the subject and the judge, and the bridge refuses Anthropic model IDs at
preflight anyway. Configure the judge's Claude independently before running.
