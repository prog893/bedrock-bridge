"""Tests for the env the CLI sets on the spawned `claude` process under --claude."""

import pytest

from bedrock_bridge import cli


def _spawned_env(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    class _Done:
        returncode = 0

    def fake_run(args: list[str], env: dict[str, str]) -> _Done:
        captured.update(env)
        return _Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        cli._run_claude(8080, None, "minimax.minimax-m2.5", None, [], None)
    return captured


# Auto mode: without this, Claude Code waits for a server-side verdict that
# Bedrock never sends, and every gated tool call fails with "no verdict".
def test_auto_mode_server_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_AUTO_MODE_SERVER", raising=False)
    assert _spawned_env(monkeypatch)["CLAUDE_CODE_AUTO_MODE_SERVER"] == "0"


def test_auto_mode_server_user_override_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_SERVER", "1")
    assert _spawned_env(monkeypatch)["CLAUDE_CODE_AUTO_MODE_SERVER"] == "1"
