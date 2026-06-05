"""Functional-test fixtures: a live bedrock-bridge proxy talking to real Bedrock.

These tests spawn the uvicorn server the same way cli.py does, POST /set-model
to configure the routed model, then exercise /v1/messages with hand-built
Anthropic payloads. They make real Converse calls, so they need AWS credentials
and the configured models enabled in the account.

Model selection (override via env):
  BEDROCK_BRIDGE_TEST_TEXT_MODEL    text-only model       (default: minimax-m2.5)
  BEDROCK_BRIDGE_TEST_IMAGE_MODEL   accepts image input   (default: kimi-k2.5)
  AWS_REGION                        region                (default: ap-northeast-1)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

REGION = os.environ.get("AWS_REGION") or "ap-northeast-1"
# minimax-m2.5 is text-only; kimi-k2.5 accepts IMAGE input. Override via env.
TEXT_ONLY_MODEL = os.environ.get("BEDROCK_BRIDGE_TEST_TEXT_MODEL", "minimax.minimax-m2.5")
TEXT_IMAGE_MODEL = os.environ.get("BEDROCK_BRIDGE_TEST_IMAGE_MODEL", "moonshotai.kimi-k2.5")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _post_json(url: str, payload: dict, timeout: float = 120.0) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # The bridge returns mapped errors as JSON bodies with a non-2xx status;
        # surface both so tests can assert on them.
        body = e.read().decode()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"_raw": body}
        return e.code, parsed


class BridgeClient:
    """Thin handle on a running proxy: where it lives, how to call it, and what
    its log file is (so a test can read the dumped failing-request path)."""

    def __init__(
        self,
        base_url: str,
        log_path: str,
        default_model: str,
        text_only_model: str,
        text_image_model: str,
    ) -> None:
        self.base_url = base_url
        self.log_path = log_path
        # The model this proxy actually spawned with; a payload that omits
        # "model" defaults to it, so image tests on bridge_image hit the
        # image-capable main model rather than silently falling back to text.
        self.default_model = default_model
        self.text_only_model = text_only_model
        self.text_image_model = text_image_model

    def messages(self, payload: dict, timeout: float = 120.0) -> tuple[int, dict]:
        body = dict(payload)
        body.setdefault("model", self.default_model)
        return _post_json(self.base_url + "/v1/messages", body, timeout=timeout)


def _require_aws() -> None:
    """Fail (not skip) if AWS is unreachable.

    Functional tests are mandatory: a machine that cannot reach AWS cannot
    verify the bridge, and that should surface as a failure rather than a
    silent skip. The error names the cause so it is actionable.
    """
    try:
        import boto3

        boto3.client("sts", region_name=REGION).get_caller_identity()
    except Exception as e:
        raise RuntimeError(
            f"functional tests require AWS access but it is unreachable "
            f"({type(e).__name__}: {e}). Configure credentials and region, "
            f"or run only the offline suite with: pytest -m 'not functional'."
        ) from e


def _spawn_bridge(main_model: str, main_supports_vision: bool) -> Iterator[BridgeClient]:
    """Start a proxy subprocess configured for one main model. Yields a
    BridgeClient; tears the subprocess down on exit."""
    port = _free_port()
    log_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"bedrock-bridge-test-{port}.log")
    log_file = open(log_path, "w", buffering=1)
    env = {**os.environ, "AWS_REGION": REGION}
    proxy = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "bedrock_bridge.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=log_file,
        stderr=log_file,
    )
    try:
        if not _wait_for_port(port):
            raise RuntimeError(f"bridge proxy did not come up on port {port}")
        base = f"http://127.0.0.1:{port}"
        status, _ = _post_json(
            base + "/set-model",
            {
                "main_model_id": main_model,
                "light_model_id": None,
                "main_supports_vision": main_supports_vision,
                "light_supports_vision": True,
            },
        )
        assert status == 200, f"/set-model returned {status}"
        yield BridgeClient(base, log_path, main_model, TEXT_ONLY_MODEL, TEXT_IMAGE_MODEL)
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
        log_file.close()


@pytest.fixture(scope="session")
def bridge() -> BridgeClient:
    """Proxy whose main model is text-only (drives the image-strip path)."""
    _require_aws()
    yield from _spawn_bridge(TEXT_ONLY_MODEL, main_supports_vision=False)


@pytest.fixture(scope="session")
def bridge_image() -> BridgeClient:
    """Proxy whose main model accepts image input (real vision path)."""
    _require_aws()
    yield from _spawn_bridge(TEXT_IMAGE_MODEL, main_supports_vision=True)
