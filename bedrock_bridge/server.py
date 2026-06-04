"""Starlette server: Anthropic Messages API to Bedrock Converse API proxy."""

from __future__ import annotations

import json
import logging
import re

import boto3
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import __version__
from .translate import (
    anthropic_to_converse,
    converse_to_anthropic,
    converse_stream_to_anthropic_events,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bedrock-bridge")
logger.setLevel(logging.INFO)


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
# Per-slot vision-capability flags. Default True so an unconfigured proxy
# does not strip images on a vision-capable model. The CLI sets these from
# its preflight result via /set-model.
_main_supports_vision: bool = True
_light_supports_vision: bool = True


def set_main_model(model_id: str):
    """Set the Bedrock model ID for primary requests."""
    global _main_model
    _main_model = model_id


def set_light_model(model_id: str | None):
    """Set the Bedrock model ID for light/background-helper requests."""
    global _light_model
    _light_model = model_id


def set_capabilities(main_vision: bool, light_vision: bool) -> None:
    global _main_supports_vision, _light_supports_vision
    _main_supports_vision = main_vision
    _light_supports_vision = light_vision


_IMAGE_CHIP_RE = re.compile(r"^\s*\[Image #\d+\]\s*$")
_LOST_IMAGE_PROMPT = (
    "[bedrock-bridge: an image was attached when this message was first sent, "
    "but Claude Code did not preserve the image bytes when this turn was "
    "recalled from history. Tell the user the image did not come through and "
    "ask them to re-attach it. Do NOT attempt to describe what was in the "
    "image; you cannot see it.]"
)


def _replace_lost_image_chips(body: dict) -> int:
    """Rewrite `[Image #N]` text chips to an explicit lost-image instruction
    when the enclosing message has no actual image content.

    Claude Code's history-recall path resends the chip text but drops the
    image bytes. Native Claude is good at inferring "I cannot see this" from
    just the chip; smaller open-weight models confabulate. This helper makes
    the lost-image situation explicit so any model can respond honestly.

    Mutates `body` in place. Returns count of chips rewritten. Live-paste
    turns (chip text plus a real image block in the same message) are left
    untouched.
    """
    rewritten = 0
    for msg in body.get("messages", []):
        if _msg_has_image(msg):
            continue  # real image present; chip text is just a label, leave alone
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text", "")
            if isinstance(text, str) and _IMAGE_CHIP_RE.match(text):
                content[i] = {"type": "text", "text": _LOST_IMAGE_PROMPT}
                rewritten += 1
    return rewritten


def _msg_has_image(msg: dict) -> bool:
    """True if this single message's content holds any image block."""
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "image":
            return True
        if btype == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                for ib in inner:
                    if isinstance(ib, dict) and ib.get("type") == "image":
                        return True
    return False


def _has_image_content(body: dict) -> bool:
    """True if any message in the body holds an image block."""
    return any(_msg_has_image(m) for m in body.get("messages", []))


def _strip_images_from_body(body: dict) -> int:
    """Replace every image block with an explicit text marker. Used on
    non-vision targets so the request still validates and the model has a
    clear signal that an image was present but unviewable, instead of
    silently missing context. Returns count of images replaced. Mutates in
    place.
    """
    image_marker = (
        "[bedrock-bridge: an image was attached at this position, but the "
        "configured Bedrock model has no vision modality. The image cannot "
        "be shown to you. Tell the user images are not supported on this "
        "model and that they need to exit and restart bedrock-bridge with a "
        "vision-capable main model to use images. Do NOT suggest /model; "
        "model selection is fixed at bridge startup. Do NOT attempt to "
        "describe the image; you cannot see it.]"
    )
    placeholder_block = {"type": "text", "text": image_marker}
    replaced = 0
    for msg in body.get("messages", []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        new_content: list = []
        for block in content:
            if not isinstance(block, dict):
                new_content.append(block)
                continue
            btype = block.get("type")
            if btype == "image":
                new_content.append(dict(placeholder_block))
                replaced += 1
                continue
            if btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    new_inner: list = []
                    for ib in inner:
                        if isinstance(ib, dict) and ib.get("type") == "image":
                            new_inner.append(dict(placeholder_block))
                            replaced += 1
                        else:
                            new_inner.append(ib)
                    block = {**block, "content": new_inner}
            new_content.append(block)
        msg["content"] = new_content
    return replaced


def _format_error(err: str, body: dict | None) -> tuple[int, str, str]:
    """Map a Bedrock error to a (status_code, error_type, message) tuple
    suitable for the Anthropic-shaped error envelope on the wire.

    Where a recovery path exists in Claude Code, rewrites the message to a
    substring it recognizes (e.g. "prompt is too long" triggers reactive
    compact; "image exceeds ... maximum" triggers stripImagesFromMessages).
    Always preserves the raw Bedrock error verbatim at the end for debugging.

    Substring matching is case-insensitive and status-agnostic in Claude Code,
    so a 400 + "prompt is too long" substring is enough to fire compact.
    """
    # Model context window full. Bedrock surfaces this as a wrapped JSON
    # error like:
    #   "This model's maximum context length is 262144 tokens. However, you
    #    requested 32000 output tokens and your prompt contains at least
    #    230145 input tokens, for a total of at least 262145 tokens..."
    # Claude Code recognizes "prompt is too long: X tokens > Y maximum" and
    # routes it to the compact recovery path. Rewrite preserving the real
    # token counts when we can extract them, so getPromptTooLongTokenGap
    # computes the right gap and compact peels enough to fit.
    ctx_match = re.search(
        r"maximum context length is (\d+).*?at least (\d+) input tokens.*?total of at least (\d+)",
        err,
        re.DOTALL,
    )
    if ctx_match:
        cap = int(ctx_match.group(1))
        total = int(ctx_match.group(3))
        message = (
            f"prompt is too long: {total} tokens > {cap} maximum. "
            f"[bedrock-bridge] model context window exceeded. Raw: {err}"
        )
        return 400, "invalid_request_error", message

    # Per-image cap (Claude on Bedrock: 5 MB; some hosts surface similar).
    # The error names the field, e.g. "messages.X.content.Y.tool_result.
    # content.Z.image.source.base64: image exceeds 5 MB maximum: A bytes >
    # B bytes". Anthropic's own client maps this to the "image too large"
    # path which strips and retries that single image. 413 + "Request too
    # large" routes through the same recovery while telling the user the
    # blame is on a single oversized payload.
    if "image exceeds" in err and "maximum" in err:
        return 413, "invalid_request_error", f"[bedrock-bridge] {err}"

    # Buffer overflow at model host (aggregate body, not a single image).
    # Observed: ValidationException wrapping
    # `{"error":{"message":"Failed to buffer the request body: length limit
    # exceeded",...}}`. This is a per-model gateway cap, separate from the
    # context window. Common trigger: many tool_result blocks (screenshots,
    # big file reads) piling up across turns. We map it to "prompt is too
    # long" so Claude Code's reactive-compact path fires and prunes
    # conversation history instead of looping on the same oversized body.
    if "Failed to buffer the request body" in err or "length limit exceeded" in err:
        body_kb = 0
        if body is not None:
            try:
                body_kb = len(json.dumps(body)) // 1024
            except Exception:
                pass
        # Synthesize the "X tokens > Y maximum" pattern getAssistantMessageFromError
        # parses to drive compaction aggressiveness. Reporting bytes-as-tokens
        # is intentionally lenient: the regex only cares about magnitude. The
        # gap ensures Claude Code peels enough turns to fit, not just one.
        actual = max(body_kb * 250, 1)
        limit = max(actual - 1000, 1)
        message = (
            f"prompt is too long: {actual} tokens > {limit} maximum. "
            f"[bedrock-bridge] Bedrock model host buffer cap reached "
            f"(~{body_kb} KB request body). This is a per-model gateway cap, "
            f"separate from the model's context window. Common cause: large "
            f"tool_result blocks (screenshots, big file reads) accumulated "
            f"across turns. Raw: {err}"
        )
        return 400, "invalid_request_error", message

    # Default: pass through with the bridge prefix so users see where the
    # message originated, plus a pointer to the issue tracker. Claude Code
    # appends its own "server-side issue, check your inference gateway" tail
    # to 500s (hardcoded, not editable here), so we lead with the actionable
    # bit: this is likely a bridge translation gap, report it.
    return 500, "api_error", (
        f"[bedrock-bridge] {err} | If this looks like a bridge bug, report it: "
        f"https://github.com/prog893/bedrock-bridge/issues"
    )


def _route_supports_vision(model_id: str) -> bool:
    """Capability lookup for a routed Bedrock model ID."""
    if model_id == _light_model:
        return _light_supports_vision
    return _main_supports_vision


def _route(model_alias: str) -> str:
    """Pick the Bedrock model ID based on what the caller asked for.

    The CLI sets ANTHROPIC_MODEL=<main_id> and ANTHROPIC_DEFAULT_HAIKU_MODEL=<light_id>
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


async def messages(request: Request):
    body = await request.json()
    stream = body.get("stream", False)

    model_alias = body.get("model", "")
    model_id = _route(model_alias)

    raw_tools = body.get("tools", [])
    logger.info(
        f"-> model_in={model_alias} -> routed={model_id} stream={stream} "
        f"tools={len(raw_tools)}"
    )
    # History-recall fixup: when Claude Code recalls a prior turn from
    # history, it resends the `[Image #N]` chip text but does not preserve
    # the image bytes. Native Claude reads the bare chip and refuses
    # gracefully; smaller open-weight models confabulate. Rewrite the chip
    # to an explicit instruction so any model can respond honestly. Skipped
    # for messages that still have a real image attached (live paste).
    n_lost = _replace_lost_image_chips(body)
    if n_lost:
        logger.info(f"history-recall fixup: rewrote {n_lost} lost-image chip(s) to explicit instruction")

    # Vision adaptation: if the routed model lacks IMAGE input modality,
    # strip every image block from the body and forward the request anyway.
    # Refusing the turn (returning a 400) corrupts Claude Code's local
    # transcript: it retains the failed user turn including the image, and
    # every subsequent text turn re-sends the same image, so we'd refuse
    # forever. By stripping and forwarding, the request succeeds, the model
    # sees an explicit text marker where each image was, and the session
    # continues normally. The model's job is to tell the user it cannot see
    # images on this configuration.
    if not _route_supports_vision(model_id) and _has_image_content(body):
        n = _strip_images_from_body(body)
        logger.info(
            f"vision adapt: stripped {n} image block(s) for non-vision model {model_id}"
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
        err_str = str(e)
        logger.error(f"Bedrock error: {err_str}")
        # On validation errors, dump the incoming body + the outgoing Converse
        # kwargs so we can reproduce offline. Images are replaced with a
        # {bytes: <len>} marker to keep the dump small.
        if "ValidationException" in err_str:
            try:
                _dump_failure(body, converse_kwargs, err_str)
            except Exception as dump_err:
                logger.warning(f"failed to dump failure: {dump_err}")
        status, err_type, message = _format_error(err_str, body)
        return JSONResponse(
            {
                "type": "error",
                "error": {"type": err_type, "message": message},
            },
            status_code=status,
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
        err_str = str(e)
        logger.error(f"Stream error: {err_str}")
        if body is not None and "ValidationException" in err_str:
            try:
                _dump_failure(body, kwargs, err_str)
            except Exception as dump_err:
                logger.warning(f"failed to dump failure: {dump_err}")
        _, err_type, message = _format_error(err_str, body)
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': err_type, 'message': message}})}\n\n"


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


async def set_model(request: Request):
    body = await request.json()
    main = body.get("main_model_id") or body.get("model_id", "")
    light = body.get("light_model_id")
    main_vision = bool(body.get("main_supports_vision", True))
    light_vision = bool(body.get("light_supports_vision", True))
    set_main_model(main)
    set_light_model(light)
    set_capabilities(main_vision, light_vision)
    logger.info(
        f"Models set: main={main} (vision={main_vision}) "
        f"light={light or 'none'} (vision={light_vision})"
    )
    return JSONResponse({
        "status": "ok",
        "main_model_id": main, "light_model_id": light,
        "main_supports_vision": main_vision, "light_supports_vision": light_vision,
    })


async def health(request: Request):
    return JSONResponse({"status": "ok"})


async def list_models(request: Request):
    """Stub Anthropic models endpoint so Claude Code's discovery call passes."""
    items = []
    if _main_model:
        items.append({"id": _main_model, "display_name": _main_model, "type": "model", "created_at": "2025-01-01T00:00:00Z"})
    if _light_model:
        items.append({"id": _light_model, "display_name": _light_model, "type": "model", "created_at": "2025-01-01T00:00:00Z"})
    return JSONResponse({"data": items})


async def complete(request: Request):
    """Handle legacy complete endpoint."""
    return JSONResponse(
        {"error": {"type": "not_supported", "message": "Use /v1/messages"}},
        status_code=400,
    )


app = Starlette(
    debug=False,
    routes=[
        Route("/v1/messages", messages, methods=["POST"]),
        Route("/v1/models", list_models, methods=["GET"]),
        Route("/v1/complete", complete, methods=["POST"]),
        Route("/set-model", set_model, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ],
)
