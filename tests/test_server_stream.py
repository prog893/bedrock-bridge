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
from botocore.exceptions import ClientError, EventStreamError

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


# converse_stream now runs before the response exists, so the client can be
# gone before the generator reads anything (Esc during the call). Starlette
# still enters the generator, which closes the stream.
def test_disconnect_before_first_read_closes_stream(client: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bedrock-bridge")
    asyncio.run(_call({**BODY, "stream": True}, disconnect_after=0))
    assert client.stream.closed.is_set()
    assert client.stream.read == 0
    assert "request_id=req-stream client disconnected" in caplog.text


# No Bedrock call may hold the event loop: other requests (the classifier,
# the title call) arrive while a main turn is running. Streamed (#36) and
# buffered (#40), each with and without the describe_image loop (an image
# sent to a text-only main model with a vision model set).
@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("stream", [True, False])
def test_bedrock_call_does_not_block_event_loop(
    client: FakeClient, monkeypatch: pytest.MonkeyPatch, stream: bool, image: bool
) -> None:
    fast_converse = client.converse

    def slow_converse(**kwargs: Any) -> dict:
        time.sleep(N_EVENTS * 0.01)  # as long as the fake stream
        return fast_converse(**kwargs)

    monkeypatch.setattr(client, "converse", slow_converse)
    body = {**BODY, "stream": stream}
    if image:
        monkeypatch.setattr(server, "_main_supports_vision", False)
        monkeypatch.setattr(server, "_vision_model", "fake.vision")
        png = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}}
        body["messages"] = [{"role": "user", "content": [png, {"type": "text", "text": "what is this?"}]}]
    ticks = 0

    async def main() -> None:
        nonlocal ticks

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        await _call(body)
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


UNSUPPORTED = "This model doesn't support the stopSequences field. Remove stopSequences and try again."


def _client_error() -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "ValidationException", "Message": UNSUPPORTED},
            "ResponseMetadata": {"RequestId": "req-error", "HTTPStatusCode": 400},
        },
        "ConverseStream",
    )


def _status(sent: list[dict]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


# Bedrock raises validation errors from the converse_stream() call itself,
# before any event. The bridge sent HTTP 200 first and reported them as an SSE
# error event (#33); they now get the mapped status, as buffered requests do.
@pytest.mark.parametrize("image", [False, True])
def test_stream_call_error_returns_mapped_status(
    client: FakeClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, image: bool
) -> None:
    called: list[str] = []

    def failing(method: str) -> Any:
        def fail(**kwargs: Any) -> NoReturn:
            called.append(method)
            raise _client_error()

        return fail

    monkeypatch.setattr(client, "converse_stream", failing("converse_stream"))
    monkeypatch.setattr(client, "converse", failing("converse"))
    monkeypatch.setattr(server, "_dump_failure", lambda *a: None)
    body = {**BODY, "stream": True}
    if image:
        # The describe_image loop runs buffered Converse calls before streaming.
        monkeypatch.setattr(server, "_main_supports_vision", False)
        monkeypatch.setattr(server, "_vision_model", "fake.vision")
        png = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}}
        body["messages"] = [{"role": "user", "content": [png]}]
    sent = asyncio.run(_call(body))
    # The describe_image loop calls buffered Converse; a text request streams.
    assert called == (["converse"] if image else ["converse_stream"])
    assert _status(sent) == 400
    error = json.loads(_body_text(sent))["error"]
    assert error["type"] == "invalid_request_error"
    assert "stopSequences" in error["message"]
    assert "Bedrock error (request_id=req-error)" in caplog.text


class FailingStream(FakeStream):
    """Raises an in-stream exception event after the first delta."""

    def __iter__(self) -> Iterator[dict]:
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "x"}}}
        raise EventStreamError(
            {"Error": {"Code": "internalServerException", "Message": "unexpected error"}}, "ConverseStream"
        )


# After the first event the status is on the wire; an error Bedrock raises
# mid-stream can only reach the client as an SSE error event.
def test_in_stream_error_is_sse_event(client: FakeClient, caplog: pytest.LogCaptureFixture) -> None:
    client.stream = FailingStream()
    sent = asyncio.run(_call({**BODY, "stream": True}))
    assert _status(sent) == 200
    text = _body_text(sent)
    assert "event: content_block_delta" in text
    assert text.rstrip().split("\n\n")[-1].startswith("event: error")
    # The exception event has no request ID of its own; the stream's is logged.
    assert "Stream error (request_id=req-stream)" in caplog.text
    assert client.stream.closed.is_set()
    assert "client disconnected" not in caplog.text


def test_request_id_sources() -> None:
    assert server._request_id({"ResponseMetadata": {"RequestId": "a"}}) == "a"
    assert server._request_id(_client_error()) == "req-error"
    assert server._request_id({}) is None
    assert server._request_id(ValueError("no response")) is None
