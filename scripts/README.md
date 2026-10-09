# scripts/

Dev-only tools. Not shipped with the installed package; run from a source checkout.

| Script | Purpose |
|--------|---------|
| `e2e_grade.py` | Drive a model through the bridge to describe a known image, then score the output against `tests/fixtures/sample_01.annotation.md` using `claude -p` as an independent judge. Exits nonzero below the score threshold. |
| `probe_tool_use.py` | Single-model raw Converse call to inspect how a given model emits `toolUse` blocks. Use when adding support for a new provider. |
| `mirror-to-aws-samples.sh` | Copy tracked files into a local `aws-samples/sample-apj-sup-sa` checkout under `ai-coding-assistants/bedrock-bridge/`, dropping repo-root-only files and rewriting the README for the mirror. Does not commit or push. |

```bash
./.venv/bin/python scripts/e2e_grade.py --model moonshotai.kimi-k2.5
./.venv/bin/python scripts/probe_tool_use.py minimax.minimax-m2.5
```

`e2e_grade.py` grades the `bedrock-bridge` installed next to the Python running it (the dev venv, so the
checkout is under test), falling back to `PATH`; set `$BEDROCK_BRIDGE_BIN` to pick another. The run
header prints which one it used.

The `claude` judge used by `e2e_grade.py` must reach Claude by a path that does
not go through this bridge (first-party Anthropic key or native
`CLAUDE_CODE_USE_BEDROCK=1`).

Hand-run compatibility-matrix probes live under `tests/manual/`; they emit a
markdown report for a human to read. See
[tests/manual/README.md](../tests/manual/README.md).
