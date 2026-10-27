"""Tests for the env the CLI sets on the spawned `claude` process under --claude."""

import pytest

from bedrock_bridge import cli


def _spawned_env(monkeypatch: pytest.MonkeyPatch, main_id: str = "minimax.minimax-m2.5") -> dict:
    captured: dict = {}

    class _Done:
        returncode = 0

    def fake_run(args: list[str], env: dict[str, str]) -> _Done:
        captured.update(env)
        return _Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        cli._run_claude(8080, None, main_id, None, [], None)
    return captured


# Auto mode: without this, Claude Code waits for a server-side verdict that
# Bedrock never sends, and every gated tool call fails with "no verdict".
def test_auto_mode_server_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_AUTO_MODE_SERVER", raising=False)
    assert _spawned_env(monkeypatch)["CLAUDE_CODE_AUTO_MODE_SERVER"] == "0"


def test_auto_mode_server_user_override_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_SERVER", "1")
    assert _spawned_env(monkeypatch)["CLAUDE_CODE_AUTO_MODE_SERVER"] == "1"


# Context window: Claude Code assumes 200K for model IDs it does not know.
# GLM 5.3 has 1M (compacted far too early); gpt-oss has 128K (compacted only
# after Bedrock rejected the request).
def test_context_window_from_profile_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_MAX_CONTEXT_TOKENS", raising=False)
    assert _spawned_env(monkeypatch, "global.zai.glm-5.3")["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_context_window_below_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_MAX_CONTEXT_TOKENS", raising=False)
    assert _spawned_env(monkeypatch, "openai.gpt-oss-120b-1:0")["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "128000"


def test_context_window_unlisted_model_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_MAX_CONTEXT_TOKENS", raising=False)
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in _spawned_env(monkeypatch, "example.unlisted-model")


def test_context_window_user_override_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "300000")
    assert _spawned_env(monkeypatch, "global.zai.glm-5.3")["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "300000"
