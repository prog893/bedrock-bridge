"""FastAPI server: Anthropic Messages API → Bedrock Converse API proxy."""

from __future__ import annotations

import json
import logging

import boto3
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from . import __version__
from .translate import (
    anthropic_to_converse,
    converse_to_anthropic,
    converse_stream_to_anthropic_events,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bedrock-bridge")
logger.setLevel(logging.INFO)

app = FastAPI(title="bedrock-bridge")

_client = None
_region = None


def get_client():
    global _client, _region
    if _client is None:
        from botocore.config import Config
        # user_agent replaces the "Boto3/... Botocore/..." prefix; user_agent_extra
        # appends. Set both so the tag is visible at the start of the UA (before any
        # CloudTrail truncation) and still appears in the extra-segment list.
        ua = f"bedrock-bridge/{__version__}"
        cfg = Config(user_agent=ua, user_agent_extra=ua)
        # region_name=None lets boto3 resolve via its standard chain
        # (AWS_REGION env, AWS_DEFAULT_REGION, profile config, IMDS).
        _client = boto3.client("bedrock-runtime", config=cfg)
        _region = _client.meta.region_name
    return _client


_main_model: str | None = None
_light_model: str | None = None


def set_main_model(model_id: str):
    """Set the Bedrock model ID for primary requests."""
    global _main_model
    _main_model = model_id


def set_light_model(model_id: str | None):
    """Set the Bedrock model ID for light/background-helper requests."""
    global _light_model
    _light_model = model_id


def _route(model_alias: str) -> str:
    """Pick the Bedrock model ID based on what the caller asked for.

    The CLI sets ANTHROPIC_MODEL=<main_id> and ANTHROPIC_SMALL_FAST_MODEL=<light_id>
    on the spawned Claude Code process, so the incoming `model` field is one
    of those two IDs verbatim. Exact match wins; "haiku" substring is the
    fallback for clients that emit Anthropic-style names without going through
    our env wiring.
    """
    if _light_model and model_alias == _light_model:
        return _light_model
    if _light_model and "haiku" in model_alias.lower():
        return _light_model
    if _main_model:
        return _main_model
    return model_alias


@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()
    stream = body.get("stream", False)

    model_alias = body.get("model", "")
    model_id = _route(model_alias)

    raw_tools = body.get("tools", [])
    tool_summary = [t.get("type") or t.get("name") for t in raw_tools]
    logger.info(
        f"→ model_in={model_alias} → routed={model_id} stream={stream} "
        f"tools({len(raw_tools)})={tool_summary}"
    )

    converse_kwargs, metadata = anthropic_to_converse(body)
    metadata["model"] = model_alias
    client = get_client()

    try:
        if stream:
            return StreamingResponse(
                _stream_response(client, model_id, converse_kwargs, metadata, body),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
        else:
            response = client.converse(modelId=model_id, **converse_kwargs)
            result = converse_to_anthropic(response, metadata)
            return JSONResponse(result)
    except Exception as e:
        logger.error(f"Bedrock error: {e}")
        # On validation errors, dump the incoming body + the outgoing Converse
        # kwargs so we can reproduce offline. Images are replaced with a
        # {bytes: <len>} marker to keep the dump small.
        if "ValidationException" in str(e):
            try:
                _dump_failure(body, converse_kwargs, str(e))
            except Exception as dump_err:
                logger.warning(f"failed to dump failure: {dump_err}")
        return JSONResponse(
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(e)},
            },
            status_code=500,
        )


async def _stream_response(client, model_id: str, kwargs: dict, metadata: dict, body: dict | None = None):
    """Call converse_stream and yield Anthropic SSE events."""
    try:
        response = client.converse_stream(modelId=model_id, **kwargs)
        stream = response.get("stream", [])
        # Per-stream state for the translator (synthesizes content_block_start
        # events for indices Bedrock never opens explicitly).
        state: dict = {}

        for event in stream:
            for event_type, data in converse_stream_to_anthropic_events(event, metadata, state):
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        yield "event: message_stop\ndata: {}\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        if body is not None and "ValidationException" in str(e):
            try:
                _dump_failure(body, kwargs, str(e))
            except Exception as dump_err:
                logger.warning(f"failed to dump failure: {dump_err}")
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'server_error', 'message': str(e)}})}\n\n"


def _dump_failure(body: dict, kwargs: dict, err: str):
    """Persist a scrubbed copy of a failing request for offline debugging."""
    import datetime, os, tempfile, uuid

    def scrub(obj):
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [scrub(v) for v in obj]
        if isinstance(obj, (bytes, bytearray)):
            return {"__bytes_len__": len(obj), "__head_hex__": bytes(obj[:16]).hex()}
        if isinstance(obj, str) and len(obj) > 400:
            return obj[:200] + f"...<{len(obj)} chars truncated>"
        return obj

    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    path = os.path.join(tempfile.gettempdir(), f"bedrock-bridge-fail-{stamp}-{uuid.uuid4().hex[:6]}.json")
    with open(path, "w") as f:
        json.dump({"error": err, "body": scrub(body), "converse_kwargs": scrub(kwargs)}, f, indent=2, default=str)
    logger.error(f"dumped failing request to {path}")


@app.post("/set-model")
async def set_model(request: Request):
    body = await request.json()
    main = body.get("main_model_id") or body.get("model_id", "")
    light = body.get("light_model_id")
    set_main_model(main)
    set_light_model(light)
    logger.info(f"Models set: main={main} light={light or 'none'}")
    return {"status": "ok", "main_model_id": main, "light_model_id": light}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    """Stub Anthropic models endpoint so Claude Code's discovery call passes."""
    items = []
    if _main_model:
        items.append({"id": _main_model, "display_name": _main_model, "type": "model", "created_at": "2025-01-01T00:00:00Z"})
    if _light_model:
        items.append({"id": _light_model, "display_name": _light_model, "type": "model", "created_at": "2025-01-01T00:00:00Z"})
    return {"data": items}


@app.post("/v1/complete")
async def complete(request: Request):
    """Handle legacy complete endpoint."""
    return JSONResponse(
        {"error": {"type": "not_supported", "message": "Use /v1/messages"}},
        status_code=400,
    )
