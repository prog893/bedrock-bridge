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

### Judge path

The subject model runs through the bridge. The judge is a separate `claude -p`
call that runs Claude natively (`CLAUDE_CODE_USE_BEDROCK=1` or a first-party API
key) and does not go through the bridge, so a translation bug cannot skew the
grade. Run the grader from a shell where `claude` is not pointed at the bridge.
