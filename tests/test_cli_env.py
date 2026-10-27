"""Tests for the env the CLI sets on the spawned `claude` process under --claude."""

import json

import pytest

from bedrock_bridge import cli


def _spawn(
    monkeypatch: pytest.MonkeyPatch,
    main_id: str = "minimax.minimax-m2.5",
    light_id: str | None = None,
    passthrough: list[str] | None = None,
) -> tuple[list[str], dict]:
    captured: dict = {}

    class _Done:
        returncode = 0

    def fake_run(args: list[str], env: dict[str, str]) -> _Done:
        captured.update(args=args, env=env)
        return _Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        cli._run_claude(8080, None, main_id, light_id, passthrough or [], None)
    return captured["args"], captured["env"]


def _spawned_env(
    monkeypatch: pytest.MonkeyPatch, main_id: str = "minimax.minimax-m2.5", light_id: str | None = None
) -> dict:
    return _spawn(monkeypatch, main_id, light_id)[1]


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


# Model slots: a user who also runs Claude Code natively on Bedrock exports
# Anthropic IDs for these. Inherited, they put an Anthropic name on the light
# slot (#27) and on /model opus or sonnet.
def test_light_slot_uses_main_without_light_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "global.anthropic.claude-haiku-5-5")
    assert _spawned_env(monkeypatch)["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "minimax.minimax-m2.5"


def test_light_slot_uses_light_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "global.anthropic.claude-haiku-5-5")
    env = _spawned_env(monkeypatch, light_id="moonshotai.kimi-k2.5")
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "moonshotai.kimi-k2.5"


@pytest.mark.parametrize(
    "key", ["ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"]
)
def test_inherited_model_slots_removed(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv(key, "global.anthropic.claude-opus-5-5")
    assert key not in _spawned_env(monkeypatch)


# A settings-file `env` block overrides the process env (measured on Claude
# Code 2.1.293 for user, project and local settings), so the same values go in
# through --settings, which outranks those files.
def test_settings_flag_pins_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    args, _ = _spawn(monkeypatch, light_id="moonshotai.kimi-k2.5")
    assert args[1] == "--settings"
    assert json.loads(args[2])["env"] == {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
        "ANTHROPIC_API_KEY": "bedrock-bridge",
        "ANTHROPIC_MODEL": "minimax.minimax-m2.5",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "moonshotai.kimi-k2.5",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "",
        "ANTHROPIC_SMALL_FAST_MODEL": "",
        "CLAUDE_CODE_USE_BEDROCK": "",
        "CLAUDE_CODE_USE_MANTLE": "",
        "CLAUDE_CODE_USE_VERTEX": "",
        "CLAUDE_CODE_USE_FOUNDRY": "",
    }


@pytest.mark.parametrize("passthrough", [["--settings", "mine.json"], ["--settings=mine.json"]])
def test_user_settings_flag_wins_with_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], passthrough: list[str]
) -> None:
    args, _ = _spawn(monkeypatch, passthrough=passthrough)
    assert args[-len(passthrough) :] == passthrough
    assert args.index("--settings") == 1
    assert "replaces the bridge's" in capsys.readouterr().err


def test_no_warning_without_user_settings_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _spawn(monkeypatch, passthrough=["--model", "haiku"])
    assert "replaces the bridge's" not in capsys.readouterr().err
