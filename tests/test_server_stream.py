"""Streaming lifecycle, event-loop use and Bedrock request IDs (#36, #40).

The app is driven through its ASGI interface with a fake boto3 client, so
Starlette's own disconnect handling runs and no AWS creds or network are used.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest
from botocore.exceptions import ClientError

from bedrock_bridge import server

N_EVENTS = 200
BODY = {"model": "fake.model", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}


class FakeStream:
    """A ConverseStream body: one text delta every 10 ms."""

    def __init__(self) -> None:
        self.read = 0
        self.closed = threading.Event()

    def __iter__(self) -> Iterator[dict]:
        yield {"messageStart": {"role": "assistant"}}
        for _ in range(N_EVENTS):
            if self.closed.is_set():
                return
            time.sleep(0.01)
            self.read += 1
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "x"}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": N_EVENTS}}}

    def close(self) -> None:
        self.closed.set()


class FakeClient:
    def __init__(self) -> None:
        self.stream = FakeStream()

    def converse_stream(self, **kwargs: Any) -> dict:
        return {"stream": self.stream, "ResponseMetadata": {"RequestId": "req-stream"}}

    def converse(self, **kwargs: Any) -> dict:
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1, "outputTokens": 1},
            "ResponseMetadata": {"RequestId": "req-buffered"},
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setattr(server, "_main_model", "fake.model")
    return fake


async def _call(body: dict, disconnect_after: float | None = None) -> list[dict]:
    """POST body to /v1/messages; optionally disconnect after a delay."""
    raw = json.dumps(body).encode()
    sent: list[dict] = []
    delivered = False

    async def receive() -> dict:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        if disconnect_after is None:
            await asyncio.Event().wait()  # never disconnects
        await asyncio.sleep(disconnect_after)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn reports
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/messages",
        "raw_path": b"/v1/messages",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
    }
    await server.app(scope, receive, send)
    return sent


def _body_text(sent: list[dict]) -> str:
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()


# Before #36 the bridge iterated the boto3 stream on the event loop: it never
# saw the disconnect, read every remaining event, and left the stream open.
def test_disconnect_stops_reading_and_closes_stream(client: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bedrock-bridge")
    asyncio.run(_call({**BODY, "stream": True}, disconnect_after=0.2))
    assert client.stream.closed.is_set()
    assert client.stream.read < N_EVENTS / 2
    assert "request_id=req-stream client disconnected" in caplog.text


# No Bedrock call may hold the event loop: other requests (the classifier,
# the title call) arrive while a main turn is running. Streamed (#36) and
# buffered (#40).
@pytest.mark.parametrize("stream", [True, False])
def test_bedrock_call_does_not_block_event_loop(
    client: FakeClient, monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    fast_converse = client.converse

    def slow_converse(**kwargs: Any) -> dict:
        time.sleep(N_EVENTS * 0.01)  # as long as the fake stream
        return fast_converse(**kwargs)

    monkeypatch.setattr(client, "converse", slow_converse)
    ticks = 0

    async def main() -> None:
        nonlocal ticks

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        await _call({**BODY, "stream": stream})
        t.cancel()

    asyncio.run(main())
    # The call takes about N_EVENTS * 10 ms; a blocked loop ticks 0 times.
    assert ticks > N_EVENTS / 4


def test_completed_stream_logs_request_id(client: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bedrock-bridge")
    sent = asyncio.run(_call({**BODY, "stream": True}))
    assert "event: message_stop" in _body_text(sent)
    assert client.stream.closed.is_set()
    assert "<- routed=fake.model stream=True request_id=req-stream\n" in caplog.text + "\n"
    assert "client disconnected" not in caplog.text


def test_buffered_response_logs_request_id(client: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bedrock-bridge")
    asyncio.run(_call(BODY))
    assert "<- routed=fake.model stream=False request_id=req-buffered" in caplog.text


def _client_error() -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "ValidationException", "Message": "bad field"},
            "ResponseMetadata": {"RequestId": "req-error", "HTTPStatusCode": 400},
        },
        "ConverseStream",
    )


def test_stream_error_logs_request_id(
    client: FakeClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**kwargs: Any) -> NoReturn:
        raise _client_error()

    monkeypatch.setattr(client, "converse_stream", fail)
    monkeypatch.setattr(server, "_dump_failure", lambda *a: None)
    sent = asyncio.run(_call({**BODY, "stream": True}))
    assert "event: error" in _body_text(sent)
    assert "Stream error (request_id=req-error)" in caplog.text
    assert "client disconnected" not in caplog.text


def test_request_id_sources() -> None:
    assert server._request_id({"ResponseMetadata": {"RequestId": "a"}}) == "a"
    assert server._request_id(_client_error()) == "req-error"
    assert server._request_id({}) is None
    assert server._request_id(ValueError("no response")) is None
