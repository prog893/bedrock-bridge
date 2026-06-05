"""Functional tests: hand-built Anthropic payloads through a live bridge to
real Bedrock. They assert on the response envelope (success shape or mapped
recovery error) and ignore the model's prose, so they stay deterministic even
though a real model answers.

All tests here are marked `functional` and make real Converse calls.
"""

import pytest

from .conftest import BridgeClient

pytestmark = pytest.mark.functional


# A plain text turn must round-trip: 200 + an assistant message with content.
def test_text_turn_succeeds(bridge: BridgeClient) -> None:
    status, body = bridge.messages(
        {
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        }
    )
    assert status == 200, body
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert isinstance(body["content"], list)


# An assistant turn that arrives as nothing but empty text blocks previously
# produced a blank-text ValidationException (the v0.1.3 hotfix). It must now
# round-trip via the "[empty]" placeholder.
def test_empty_assistant_turn_does_not_500(bridge: BridgeClient) -> None:
    status, body = bridge.messages(
        {
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": ""},
                        {"type": "text", "text": ""},
                    ],
                },
                {"role": "user", "content": "now reply with OK"},
            ],
        }
    )
    assert status == 200, body
    assert body["type"] == "message"


# A tool name with characters outside Bedrock's [a-zA-Z0-9_-] charset must be
# sanitized by the bridge so Bedrock accepts it. We send a tool definition plus
# a forcing prompt; success means no 400 charset ValidationException.
def test_illegal_tool_name_is_sanitized(bridge: BridgeClient) -> None:
    status, body = bridge.messages(
        {
            "max_tokens": 128,
            "tools": [
                {
                    "name": "mcp__server__do something(weird)",  # spaces + parens: illegal
                    "description": "Echo a value back.",
                    "input_schema": {"type": "object", "properties": {"v": {"type": "string"}}},
                }
            ],
            "messages": [{"role": "user", "content": "Call the tool with v='hi'."}],
        }
    )
    # Either the model calls the tool (200) or declines (200); what must NOT
    # happen is a Bedrock charset rejection bubbling through as an error.
    assert status == 200, body
    blob = str(body)
    assert "satisfy regular expression pattern" not in blob
    assert "ValidationException" not in blob


# An image sent to a text-only main model must not 500 with "doesn't support
# the image content block": the bridge strips images to a text marker and the
# turn succeeds.
def test_image_to_text_only_model_is_stripped(bridge: BridgeClient) -> None:
    status, body = bridge.messages(
        {
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe what you can see, if anything."},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _RED_PIXEL}},
                    ],
                }
            ],
        }
    )
    assert status == 200, body
    assert "doesn't support the image" not in str(body)


# An image inside a tool_result, sent to an image-capable model, must round-trip
# (this is the shape that previously broke kimi/minimax: image nested in
# toolResult). The bridge hoists it to a sibling block.
def test_image_in_tool_result_roundtrips_on_image_model(bridge_image: BridgeClient) -> None:
    status, body = bridge_image.messages(
        {
            "max_tokens": 64,
            # Bedrock requires toolConfig whenever messages carry toolUse/toolResult
            # blocks; Claude Code always sends the tools array, so the test does too.
            "tools": [
                {
                    "name": "screenshot",
                    "description": "Capture a screenshot.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "messages": [
                {"role": "user", "content": "Look at the tool output."},
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "toolu_1", "name": "screenshot", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": "image/png", "data": _RED_PIXEL},
                                },
                            ],
                        },
                    ],
                },
            ],
        }
    )
    assert status == 200, body
    assert "doesn't support the image" not in str(body)


# A streaming text turn must produce a well-formed SSE stream ending without a
# bridge error. We assert the bridge accepts the stream request (200) and the
# body carries event frames.
def test_streaming_text_turn(bridge: BridgeClient) -> None:
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        bridge.base_url + "/v1/messages",
        data=_json.dumps(
            {
                "model": bridge.text_only_model,
                "max_tokens": 64,
                "stream": True,
                "messages": [{"role": "user", "content": "Reply with OK."}],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        assert resp.status == 200
        raw = resp.read().decode()
    assert "event: message_start" in raw
    assert "event: message_stop" in raw
    assert "ValidationException" not in raw


# 1x1 red PNG, base64. Smallest valid image payload; contents are irrelevant
# for these tests, which assert on envelope shape rather than perception.
_RED_PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
