"""Regression tests for translate.py.

Each test is keyed to a concrete Bedrock-shape rejection or translation bug we
hit in the field. Inputs are hand-built minimal Anthropic/Bedrock payloads
(no captured session data) so the public repo carries no PII.
"""

import pytest

from bedrock_bridge import translate
from bedrock_bridge.translate import (
    _EMPTY_TEXT_PLACEHOLDER,
    anthropic_to_converse,
    converse_stream_to_anthropic_events,
)


def _converted_messages(body: dict) -> list[dict]:
    kwargs, _ = anthropic_to_converse(body)
    return kwargs["messages"]


# Bedrock rejects blank text blocks ("text field ... is blank"). An interrupted
# assistant turn can arrive as nothing but empty text blocks; every real block
# is dropped, so the all-empty fallback must emit a non-blank placeholder.
def test_empty_turn_uses_nonblank_placeholder() -> None:
    body = {
        "model": "m",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": ""},
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    assert msgs[0]["content"] == [{"text": _EMPTY_TEXT_PLACEHOLDER}]
    assert _EMPTY_TEXT_PLACEHOLDER != ""


# A real text block alongside empties keeps the real text and drops the empties;
# no placeholder is added.
def test_empty_text_blocks_dropped_when_real_content_present() -> None:
    body = {
        "model": "m",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "actual answer"},
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    assert msgs[0]["content"] == [{"text": "actual answer"}]


# An empty tool_result (string or list) must fall back to a non-blank
# placeholder; Bedrock rejects an empty toolResult.content list.
def test_empty_tool_result_uses_nonblank_placeholder() -> None:
    body = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "abc", "content": ""},
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    tr = msgs[0]["content"][0]["toolResult"]
    assert tr["content"] == [{"text": _EMPTY_TEXT_PLACEHOLDER}]


# Some Bedrock models reject images nested in toolResult. We hoist the image to
# a sibling block in the same user message and leave a text marker behind.
def test_image_hoisted_out_of_tool_result() -> None:
    png_b64 = "aGVsbG8="  # "hello"
    body = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "abc",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
                        ],
                    },
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    content = msgs[0]["content"]
    tr = next(b["toolResult"] for b in content if "toolResult" in b)
    # The image is gone from the tool result, replaced by a text marker.
    assert all("image" not in sub for sub in tr["content"])
    assert any("text" in sub for sub in tr["content"])
    # And it now appears as a sibling image block.
    assert any("image" in b for b in content)


# image/jpg is not a valid Bedrock format; it must be normalized to jpeg.
def test_jpg_media_type_normalized_to_jpeg() -> None:
    body = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpg", "data": "aGk="}},
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    assert msgs[0]["content"][0]["image"]["format"] == "jpeg"


# stop_sequences is rejected by every non-Anthropic Bedrock model; drop it.
def test_stop_sequences_dropped() -> None:
    body = {"model": "m", "messages": [], "stop_sequences": ["X"], "max_tokens": 10}
    kwargs, _ = anthropic_to_converse(body)
    assert "stopSequences" not in kwargs.get("inferenceConfig", {})


# Anthropic server-side tools have no Bedrock equivalent and must be dropped;
# a tools list that is only server tools yields no toolConfig (Bedrock rejects
# an empty tools list).
def test_server_tools_dropped_no_toolconfig() -> None:
    body = {
        "model": "m",
        "messages": [],
        "tools": [{"type": "web_search_20250101", "name": "web_search"}],
    }
    kwargs, _ = anthropic_to_converse(body)
    assert "toolConfig" not in kwargs


# Tool names over Bedrock's 64-char cap are shortened deterministically and the
# mapping round-trips on the response leg.
def test_long_tool_name_shortened_and_restored() -> None:
    long_name = "mcp__some_server__" + "x" * 80
    short = translate._shorten_tool_name(long_name)
    assert len(short) <= 64
    assert translate._restore_tool_name(short) == long_name


# Some models (Kimi) emit tool names/IDs with chat-template tokens leaked in
# (spaces, "<|...|>"), violating Bedrock's charset even when under the length
# cap. A short-but-illegal value must still be rewritten, and round-trip.
def test_illegal_charset_tool_name_shortened_even_when_short() -> None:
    bad_name = "tool with spaces"  # short, but space is illegal for names
    short = translate._shorten_tool_name(bad_name)
    assert translate._NAME_ILLEGAL.search(short) is None
    assert translate._restore_tool_name(short) == bad_name


def test_illegal_charset_tool_use_id_shortened_even_when_short() -> None:
    bad_id = "call<|tool|> 7"  # short, but "<", "|", ">", " " are illegal for IDs
    short = translate._shorten_tool_use_id(bad_id)
    assert translate._ID_ILLEGAL.search(short) is None
    assert translate._restore_tool_use_id(short) == bad_id


# A tool_use and its matching tool_result must resolve to the same shortened
# id, so Bedrock can pair them. (messages.N.toolUse / messages.N+1.toolResult)
def test_tool_use_and_result_share_shortened_id() -> None:
    raw_id = "functions.mcp__server__some_tool:" + "1" * 80
    body = {
        "model": "m",
        "messages": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": raw_id, "name": "t", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": raw_id, "content": "ok"}]},
        ],
    }
    msgs = _converted_messages(body)
    use_id = msgs[0]["content"][0]["toolUse"]["toolUseId"]
    res_id = msgs[1]["content"][0]["toolResult"]["toolUseId"]
    assert use_id == res_id
    assert len(use_id) <= 64


# A real image's base64 payload must decode to the raw bytes Bedrock expects.
# 1x1 red PNG; we know exactly what it is.
_RED_PIXEL_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_image_base64_decoded_to_bytes() -> None:
    import base64 as _b64

    body = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": _RED_PIXEL_PNG_B64},
                    }
                ],
            },
        ],
    }
    msgs = _converted_messages(body)
    img = msgs[0]["content"][0]["image"]
    assert img["format"] == "png"
    assert img["source"]["bytes"] == _b64.b64decode(_RED_PIXEL_PNG_B64)
    assert isinstance(img["source"]["bytes"], (bytes, bytearray))


# kimi-k2 and similar skip contentBlockStart for text/reasoning. The translator
# must synthesize a content_block_start on the first delta of an unseen index,
# else Claude Code renders reasoning as plain text.
def test_stream_synthesizes_content_block_start_for_text() -> None:
    state = {}
    event = {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "hello"}}}
    out = list(converse_stream_to_anthropic_events(event, {"model": "m"}, state))
    types = [e[0] for e in out]
    assert types == ["content_block_start", "content_block_delta"]
    assert out[0][1]["content_block"]["type"] == "text"


# Some models prefix the first delta with a single space (chat-template
# artifact). Strip exactly one leading space on the first delta, keep the rest.
def test_stream_strips_single_leading_space_once() -> None:
    state = {}
    e1 = {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": " hi"}}}
    e2 = {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "  there"}}}
    out1 = list(converse_stream_to_anthropic_events(e1, {"model": "m"}, state))
    out2 = list(converse_stream_to_anthropic_events(e2, {"model": "m"}, state))
    d1 = next(e[1] for e in out1 if e[0] == "content_block_delta")
    d2 = next(e[1] for e in out2 if e[0] == "content_block_delta")
    assert d1["delta"]["text"] == "hi"  # one leading space stripped
    assert d2["delta"]["text"] == "  there"  # later deltas untouched


# The trailing Converse metadata event carries inputTokens and outputTokens.
# We forward both on the final message_delta so the client can report the real
# per-response input count instead of a hardcoded 0.
def test_stream_metadata_forwards_input_tokens() -> None:
    event = {"metadata": {"usage": {"inputTokens": 1500, "outputTokens": 800}}}
    out = list(converse_stream_to_anthropic_events(event, {"model": "m"}, {}))
    usage = next(e[1]["usage"] for e in out if e[0] == "message_delta")
    assert usage["input_tokens"] == 1500
    assert usage["output_tokens"] == 800
    # No cache counts in the event: report 0.
    assert usage["cache_read_input_tokens"] == 0
    assert usage["cache_creation_input_tokens"] == 0


# Models with implicit prompt caching (GLM 5.3 reported inputTokens 2 with
# cacheReadInputTokens 2106) must surface the cached counts: Claude Code sums
# input + cache fields for its context gauge and auto-compact trigger, and
# dropping them made it see a 2-token context.
def test_stream_metadata_forwards_cache_tokens() -> None:
    event = {
        "metadata": {
            "usage": {"inputTokens": 2, "outputTokens": 42, "cacheReadInputTokens": 2106, "cacheWriteInputTokens": 7}
        }
    }
    out = list(converse_stream_to_anthropic_events(event, {"model": "m"}, {}))
    usage = next(e[1]["usage"] for e in out if e[0] == "message_delta")
    assert usage == {
        "input_tokens": 2,
        "output_tokens": 42,
        "cache_read_input_tokens": 2106,
        "cache_creation_input_tokens": 7,
    }


def test_buffered_response_forwards_cache_tokens() -> None:
    response = {
        "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 2, "outputTokens": 1, "cacheReadInputTokens": 2106, "cacheWriteInputTokens": 0},
    }
    usage = translate.converse_to_anthropic(response, {"model": "m"})["usage"]
    assert usage["cache_read_input_tokens"] == 2106
    assert usage["cache_creation_input_tokens"] == 0


# Bedrock streams messageStop (stopReason tool_use) and then metadata (usage).
# The metadata message_delta used to hardcode stop_reason end_turn, and the
# client keeps the last one, so streamed tool calls ended as end_turn. Event
# sequence from a glm-5.3 Read-tool probe.
def test_stream_tool_use_stop_reason_survives_metadata() -> None:
    state: dict = {}
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "call_0", "name": "Read"}}, "contentBlockIndex": 0}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"file_path":"/tmp/x"}'}}, "contentBlockIndex": 0}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": {"inputTokens": 2, "outputTokens": 42}}},
    ]
    deltas = [
        data
        for ev in events
        for etype, data in converse_stream_to_anthropic_events(ev, {"model": "m"}, state)
        if etype == "message_delta"
    ]
    assert [d["delta"]["stop_reason"] for d in deltas] == ["tool_use", "tool_use"]


# Claude Code sends its "# Environment" block as a `role: "system"` entry at the
# end of `messages` (the Anthropic API's mid-conversation system message).
# Converse has no system role: Bedrock rejects the final-entry case with
# "requires the last turn in the conversation to be a user message" and the
# mid-history case with "This model doesn't support system messages". The entry
# must become a tagged text block on the preceding user turn.
def test_system_role_last_entry_folded_into_preceding_user_turn() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "system", "content": [{"type": "text", "text": "# Environment\ncwd: /tmp"}]},
        ],
    }
    kwargs, metadata = anthropic_to_converse(body)
    msgs = kwargs["messages"]
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"] == [
        {"text": "hi"},
        {"text": "<system-reminder>\n# Environment\ncwd: /tmp\n</system-reminder>"},
    ]
    assert metadata["system_messages_folded"] == 1


# String-form content on both sides folds the same way.
def test_system_role_string_content_folded() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "env"},
        ],
    }
    msgs = _converted_messages(body)
    assert msgs == [
        {"role": "user", "content": [{"text": "hi"}, {"text": "<system-reminder>\nenv\n</system-reminder>"}]}
    ]


# A system entry between a user turn and the assistant reply (the other
# placement the Anthropic API allows) attaches to the user turn before it, so
# user/assistant alternation is unchanged.
def test_system_role_mid_history_keeps_alternation() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "q1"},
            {"role": "system", "content": "env"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ],
    }
    msgs = _converted_messages(body)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"][1]["text"].startswith("<system-reminder>")
    assert msgs[2]["content"] == [{"text": "q2"}]


# Defensive placements the API forbids but a client might still emit: with no
# user turn before it, the entry is prepended to the next user turn; after an
# assistant turn with nothing following, it becomes its own user turn so the
# request still ends on a user message.
def test_system_role_without_preceding_user_turn_prepended_to_next() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "env"},
            {"role": "user", "content": "hi"},
        ],
    }
    msgs = _converted_messages(body)
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"] == [{"text": "<system-reminder>\nenv\n</system-reminder>"}, {"text": "hi"}]


def test_system_role_after_assistant_becomes_own_user_turn() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "system", "content": "env"},
        ],
    }
    msgs = _converted_messages(body)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[2]["content"] == [{"text": "<system-reminder>\nenv\n</system-reminder>"}]


# Effort-only system messages carry `content: []`; there is nothing to carry
# over, so the entry is removed without adding a placeholder block.
def test_empty_system_role_entry_dropped() -> None:
    body = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": []},
        ],
    }
    kwargs, metadata = anthropic_to_converse(body)
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert metadata["system_messages_folded"] == 1


# Claude Code sends `output_config.effort`; Converse has no standard field, so
# it is mapped to `reasoning_effort` in additionalModelRequestFields only for
# models measured to take it.
def _effort_fields(model_id: str | None, effort: str | None) -> dict | None:
    body: dict = {"model": "m", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]}
    if effort is not None:
        body["output_config"] = {"effort": effort}
    kwargs, _ = anthropic_to_converse(body, model_id)
    return kwargs.get("additionalModelRequestFields")


# GLM 5.3 takes low/high/max (omitting the field means max). Levels it lacks
# go to the highest supported value below them: medium -> low, xhigh -> high.
def test_effort_glm_5_3_maps_to_low_high_max() -> None:
    got = {lvl: _effort_fields("global.zai.glm-5.3", lvl) for lvl in ("low", "medium", "high", "xhigh", "max")}
    assert got == {
        "low": {"reasoning_effort": "low"},
        "medium": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "xhigh": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "max"},
    }


# Models whose Bedrock validator stops at high reject xhigh and max with a
# ValidationException; both go to high.
def test_effort_capped_to_high_for_up_to_high_models() -> None:
    for model_id in (
        "zai.glm-5",
        "zai.glm-4.7-flash",
        "moonshotai.kimi-k2.5",
        "moonshot.kimi-k2-thinking",
        "qwen.qwen3-235b-a22b-2507-v1:0",
        "mistral.magistral-small-2509",
        "deepseek.v3.2",
        "minimax.minimax-m2.5",
    ):
        assert _effort_fields(model_id, "medium") == {"reasoning_effort": "medium"}
        assert _effort_fields(model_id, "xhigh") == {"reasoning_effort": "high"}
        assert _effort_fields(model_id, "max") == {"reasoning_effort": "high"}


# A substitution is logged as a warning once per (model, level), naming the
# supported values; supported levels log nothing.
def test_effort_substitution_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    translate._effort_substituted_warned.clear()
    with caplog.at_level("WARNING", logger="bedrock-bridge"):
        for _ in range(3):
            _effort_fields("zai.glm-5", "max")
        _effort_fields("zai.glm-5", "high")
        _effort_fields("global.zai.glm-5.3", "xhigh")
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == [
        "effort 'max' is not supported by zai.glm-5; using 'high' (supported: low, medium, high)",
        "effort 'xhigh' is not supported by global.zai.glm-5.3; using 'high' (supported: low, high, max)",
    ]


# Unlisted models are unmeasured: no field. No effort in the request, an
# unknown level, or no routed model: no field.
def test_effort_not_sent_when_unsupported_or_absent() -> None:
    assert _effort_fields("qwen.qwen3-coder-480b-a35b-v1:0", "high") is None
    assert _effort_fields("zai.glm-5.3x", "high") is None
    assert _effort_fields("zai.glm-5", None) is None
    assert _effort_fields("zai.glm-5", "ultra") is None
    assert _effort_fields(None, "high") is None


# A malformed output_config (not an object) must be ignored, not raise before
# the server's Bedrock error handling runs.
def test_effort_ignores_non_object_output_config() -> None:
    body = {"model": "m", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}], "output_config": "max"}
    kwargs, _ = anthropic_to_converse(body, "zai.glm-5")
    assert "additionalModelRequestFields" not in kwargs


# Kimi K3 and Grok 4.7 accept reasoning_effort on Converse but discard it (even
# malformed values pass), so no field is sent and the drop is logged once per
# model.
def test_effort_dropped_with_warning_for_converse_discarding_models(caplog: pytest.LogCaptureFixture) -> None:
    translate._effort_dropped_warned.clear()
    with caplog.at_level("WARNING", logger="bedrock-bridge"):
        for _ in range(2):
            assert _effort_fields("global.moonshotai.kimi-k3", "high") is None
        assert _effort_fields("global.xai.grok-4.7", "max") is None
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == [
        "effort 'high' ignored for global.moonshotai.kimi-k3: the model discards reasoning_effort on Converse",
        "effort 'max' ignored for global.xai.grok-4.7: the model discards reasoning_effort on Converse",
    ]


# --strip-reasoning-history (opt-in): thinking blocks are removed from every
# assistant turn in the request, including turns inside the current tool loop
# (Kimi K3's Bedrock card: "remove reasoning blocks from prior turns").
def _tool_loop_body() -> dict:
    return {
        "model": "m",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "read the file"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "I should read it.", "signature": ""},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x"}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "data"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "redacted_thinking", "data": "b3BhcXVl"},
                    {"type": "thinking", "thinking": "Now summarize.", "signature": ""},
                ],
            },
            {"role": "user", "content": "thanks"},
        ],
    }


def _has_reasoning(kwargs: dict) -> bool:
    return any("reasoningContent" in b for m in kwargs["messages"] for b in m["content"])


def test_reasoning_history_kept_by_default() -> None:
    kwargs, metadata = anthropic_to_converse(_tool_loop_body())
    assert _has_reasoning(kwargs)
    assert metadata["reasoning_blocks_stripped"] == 0


def test_reasoning_history_stripped_from_every_assistant_turn() -> None:
    kwargs, metadata = anthropic_to_converse(_tool_loop_body(), strip_reasoning_history=True)
    assert not _has_reasoning(kwargs)
    assert metadata["reasoning_blocks_stripped"] == 3
    # Tool calls and user turns are untouched.
    assert kwargs["messages"][1]["content"] == [
        {"toolUse": {"toolUseId": "t1", "name": "Read", "input": {"file_path": "/x"}}}
    ]
    # The turn that held only reasoning is dropped and the user turns around it
    # merge, so alternation holds and no "[empty]" placeholder is sent (GLM 5.3
    # echoed that placeholder back as its answer in a real session).
    assert [m["role"] for m in kwargs["messages"]] == ["user", "assistant", "user"]
    merged = kwargs["messages"][2]["content"]
    assert merged[0]["toolResult"]["toolUseId"] == "t1"
    assert merged[-1] == {"text": "thanks"}
    assert all(b != {"text": _EMPTY_TEXT_PLACEHOLDER} for m in kwargs["messages"] for b in m["content"])


# GLM streams an empty text delta before its reasoning, so a reasoning-only
# turn arrives as thinking plus an empty text block. It counts as reasoning-only.
def test_reasoning_only_turn_with_empty_text_is_dropped() -> None:
    body = {
        "model": "m",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "thinking", "thinking": "Nothing to say.", "signature": ""},
                ],
            },
            {"role": "user", "content": "again"},
        ],
    }
    kwargs, metadata = anthropic_to_converse(body, strip_reasoning_history=True)
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "hi"}, {"text": "again"}]}]
    assert metadata["reasoning_blocks_stripped"] == 1


# An assistant turn with visible text keeps that text; only the reasoning goes.
def test_reasoning_stripped_text_kept() -> None:
    body = {
        "model": "m",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Greet back.", "signature": ""},
                    {"type": "text", "text": "Hello!"},
                ],
            },
            {"role": "user", "content": "again"},
        ],
    }
    kwargs, _ = anthropic_to_converse(body, strip_reasoning_history=True)
    assert kwargs["messages"][1] == {"role": "assistant", "content": [{"text": "Hello!"}]}


# String-form content that is empty used to pass through as a blank text block,
# which Converse rejects in a user turn ("The text field in the ContentBlock ...
# is blank"). A user turn gets the placeholder; blank assistant text was
# accepted when measured (2026-10-09), so it is kept as is.
def test_empty_string_content_uses_placeholder() -> None:
    body = {
        "model": "m",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "hi"},
        ],
    }
    msgs = _converted_messages(body)
    assert msgs[0]["content"] == [{"text": _EMPTY_TEXT_PLACEHOLDER}]
    assert msgs[1]["content"] == [{"text": ""}]
    assert msgs[2]["content"] == [{"text": "hi"}]
