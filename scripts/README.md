# scripts/

Dev-only probes for verifying the compatibility matrix. Not shipped with the Homebrew install; run from a source checkout.

| Script | Purpose |
|--------|---------|
| `compat_matrix.py` | Direct Bedrock Converse probes per model (text, tool_use, image-in-tool-result, stream). No bridge or Claude Code involved. Fastest signal on whether a model accepts the request shapes. |
| `matrix_e2e.py` | End-to-end: spawns `bedrock-bridge` plus a real Claude Code `--print` session per model, classifies result by tailing the bridge log. Slower; covers what `compat_matrix.py` cannot. |
| `probe_tool_use.py` | Single-model raw Converse call to inspect how a given model emits `toolUse` blocks. Use when adding support for a new provider. |

Run from the repo root with the project venv:

```bash
./.venv/bin/python scripts/compat_matrix.py --region ap-northeast-1
./.venv/bin/python scripts/matrix_e2e.py --only kimi qwen
./.venv/bin/python scripts/probe_tool_use.py minimax.minimax-m2.5
```

Output of `matrix_e2e.py` lands in `/tmp/bridge_matrix.md`; per-run bridge logs in `/tmp/bedrock-bridge-<port>.log`.
