#!/usr/bin/env python3
"""bedrock-bridge CLI."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, NoRegionError

from . import __version__


LOGO = r"""
  ┌─────────────────────────────────┐
  │  bedrock-bridge                 │
  │  Anthropic API ↔ Bedrock Bridge │
  └─────────────────────────────────┘
"""

ENV_MAIN = "BEDROCK_BRIDGE_MODEL"
ENV_LIGHT = "BEDROCK_BRIDGE_MODEL_LIGHT"

# Inference-profile ID prefixes; non-region-pinned cross-region invocation.
_PROFILE_PREFIXES = ("global.", "us.", "eu.", "apac.", "apne1.", "apne2.", "apne3.")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def normalize_model_id(model_id: str) -> str:
    """Anthropic foundation IDs require a `global.` inference-profile prefix on Bedrock.

    Pass non-Anthropic IDs and already-prefixed IDs through unchanged.
    """
    if model_id.startswith("anthropic."):
        return "global." + model_id
    return model_id


def is_inference_profile(model_id: str) -> bool:
    return model_id.startswith(_PROFILE_PREFIXES)


def _model_supports_vision(bedrock_client, model_id: str) -> bool:
    """Probe whether a Bedrock model accepts IMAGE input.

    Foundation IDs map directly to GetFoundationModel. Inference-profile IDs
    name a virtual route; we resolve them to the underlying foundation model
    via the first entry in the profile's models list, then describe that.
    """
    try:
        if is_inference_profile(model_id):
            prof = bedrock_client.get_inference_profile(inferenceProfileIdentifier=model_id)
            models = prof.get("models", [])
            if not models:
                return False
            arn = models[0].get("modelArn", "")
            fm_id = arn.rsplit("/", 1)[-1] if "/" in arn else arn
            if not fm_id:
                return False
            r = bedrock_client.get_foundation_model(modelIdentifier=fm_id)
        else:
            r = bedrock_client.get_foundation_model(modelIdentifier=model_id)
        modalities = r.get("modelDetails", {}).get("inputModalities", [])
        return "IMAGE" in modalities
    except Exception:
        # If the capability lookup itself fails, assume vision-capable rather
        # than reject all image-bearing turns up front. The actual call will
        # surface a real error if the model genuinely rejects images.
        return True


def preflight(region: str | None, main_id: str, light_id: str | None) -> dict:
    """Verify credentials, region, and per-model access before serving traffic.

    Fail-fast with a clear message; let AWS error strings surface verbatim.
    Returns a dict of capability flags to forward to the proxy.
    """
    print("  Preflight:")

    # Step 1: identity
    try:
        sts = boto3.client("sts", region_name=region) if region else boto3.client("sts")
        ident = sts.get_caller_identity()
        principal = ident.get("Arn", "?").rsplit("/", 1)[-1] or ident.get("Arn", "?")
        print(f"    ✓ identity: {ident.get('Account', '?')} / {principal}")
    except NoCredentialsError:
        _fatal("no AWS credentials found. Configure a profile (`aws configure sso`), env vars, or an IMDS role.")
    except (ClientError, BotoCoreError) as e:
        _fatal(f"sts:GetCallerIdentity failed: {e}")

    # Step 2: region
    if not region:
        _fatal(f"no AWS region resolved. Set AWS_REGION, pick a profile with a region, or pass --region.")
    print(f"    ✓ region: {region}")

    # Step 3: model access
    try:
        bedrock = boto3.client("bedrock", region_name=region)
    except (ClientError, BotoCoreError) as e:
        _fatal(f"could not construct bedrock client: {e}")

    capabilities: dict = {}
    for label, mid in (("main", main_id), ("light", light_id)):
        if not mid:
            continue
        try:
            if is_inference_profile(mid):
                bedrock.get_inference_profile(inferenceProfileIdentifier=mid)
            else:
                bedrock.get_foundation_model(modelIdentifier=mid)
        except (ClientError, BotoCoreError) as e:
            _fatal(f"{label} model {mid} not accessible: {e}")

        vision = _model_supports_vision(bedrock, mid)
        capabilities[f"{label}_supports_vision"] = vision
        modalities = "text, image" if vision else "text"
        print(f"    ✓ {label}: {mid} ({modalities})")

    return capabilities


def _fatal(msg: str) -> None:
    print(f"    ✗ {msg}", file=sys.stderr)
    sys.exit(1)


def _refuse_anthropic(model_id: str, slot: str) -> None:
    """bedrock-bridge exists to run non-Claude models. For Claude on Bedrock,
    Claude Code already speaks Bedrock natively; using the bridge adds a hop
    for no benefit and breaks features the bridge drops (e.g. stopSequences,
    extended-thinking flags). Refuse early with a pointer to the native path.
    """
    if model_id.startswith(("anthropic.", "global.anthropic.", "us.anthropic.",
                            "eu.anthropic.", "apac.anthropic.")):
        print(
            f"    ✗ {slot} model {model_id} is an Anthropic Claude model. "
            f"bedrock-bridge does not serve Claude. Claude Code talks to "
            f"Bedrock natively.\n"
            f"      Use direct Bedrock mode instead:\n"
            f"        export CLAUDE_CODE_USE_BEDROCK=1\n"
            f"        export ANTHROPIC_MODEL={model_id}\n"
            f"        claude\n"
            f"      Docs: https://code.claude.com/docs/en/amazon-bedrock",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_launch(args: argparse.Namespace) -> None:
    main_raw = args.model or os.environ.get(ENV_MAIN, "")
    if not main_raw:
        _fatal(f"no main model. Pass --model or set {ENV_MAIN}.")
    _refuse_anthropic(main_raw, "main")
    light_raw = args.model_light or os.environ.get(ENV_LIGHT)
    if light_raw:
        _refuse_anthropic(light_raw, "light")
    main_id = normalize_model_id(main_raw)
    light_id = normalize_model_id(light_raw) if light_raw else None

    region = _resolve_region(args.region)
    port = find_free_port()

    print(LOGO)
    print(f"  Main:   {main_id}")
    if light_id:
        print(f"  Light:  {light_id}")
    print(f"  Proxy:  http://127.0.0.1:{port}")
    print()

    capabilities = preflight(region, main_id, light_id)
    print()

    log_path = os.path.join(tempfile.gettempdir(), f"bedrock-bridge-{port}.log")
    log_file = open(log_path, "w", buffering=1)

    proxy_env = os.environ.copy()
    if region:
        proxy_env["AWS_REGION"] = region
    proxy = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "bedrock_bridge.server:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        env=proxy_env,
        stdout=log_file,
        stderr=log_file,
    )

    def cleanup(*_):
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
        log_file.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print(f"  Logs:   {log_path}")
    print("  Starting proxy...", end=" ", flush=True)
    if not wait_for_server(port):
        print("FAILED")
        proxy.terminate()
        sys.exit(1)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/set-model",
        data=json.dumps({
            "main_model_id": main_id,
            "light_model_id": light_id,
            "main_supports_vision": capabilities.get("main_supports_vision", True),
            "light_supports_vision": capabilities.get("light_supports_vision", True),
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)
    print("OK")
    print()

    if args.claude:
        _run_claude(port, region, main_id, light_id, args.passthrough, args.print)
    else:
        _hold(port, main_id, region, proxy)


def _run_claude(
    port: int,
    region: str | None,
    main_id: str,
    light_id: str | None,
    passthrough: list[str],
    print_arg: str | None,
) -> None:
    claude_env = {
        **os.environ,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
        "ANTHROPIC_API_KEY": "bedrock-bridge",
        # ANTHROPIC_MODEL fills Claude Code's primary slot; ANTHROPIC_DEFAULT_HAIKU_MODEL
        # fills the light slot used by background tasks (auto-mode classifier,
        # session title generation, summarization). The bridge routes both back to
        # the configured Bedrock IDs by exact-string match in server._route.
        "ANTHROPIC_MODEL": main_id,
        # Claude Code treats our proxy as the Anthropic API (since we set
        # ANTHROPIC_BASE_URL), so the "Claude API" defaults apply: telemetry,
        # Sentry, /feedback, autoupdater, and surveys are all on by default.
        # The umbrella opt-out turns them off so a Bedrock-backed session phones
        # home no more than a native CLAUDE_CODE_USE_BEDROCK=1 session would.
        # Local state (session transcripts, /cost, auto-memory) is unaffected.
        # Users can override by exporting CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=0.
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": os.environ.get(
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1"
        ),
    }
    if light_id:
        claude_env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = light_id
    if region:
        claude_env["AWS_REGION"] = region
    for key in (
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_MANTLE",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ):
        claude_env.pop(key, None)

    claude_args = ["claude"]
    if print_arg:
        claude_args += ["--print", print_arg]
    if passthrough:
        claude_args += passthrough

    print(f"  Launching: {' '.join(claude_args)}")
    print("  ─" * 20)
    print()

    result = subprocess.run(claude_args, env=claude_env)
    sys.exit(result.returncode)


def _hold(port: int, main_id: str, region: str | None, proxy: subprocess.Popen) -> None:
    """Print the env wiring users need and block until interrupted."""
    print("  Proxy is running. Wire any Anthropic-API client to:")
    print()
    print(f"    export ANTHROPIC_BASE_URL=http://127.0.0.1:{port}")
    print(f"    export ANTHROPIC_API_KEY=bedrock-bridge")
    print()
    print(f"  Tell the client to request model id: {main_id}")
    if region:
        print(f"  Region pinned for this proxy: {region}")
    print()
    print("  Press Ctrl-C to stop.")
    try:
        proxy.wait()
    except KeyboardInterrupt:
        pass


def _resolve_region(cli_region: str | None) -> str | None:
    """Resolve AWS region: CLI flag > AWS_REGION/AWS_DEFAULT_REGION > active profile.

    Returns None only if boto3's chain finds nothing.
    """
    if cli_region:
        return cli_region
    try:
        return boto3.Session().region_name
    except Exception:
        return None


def _build_launch_parser(prog: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description="Bridge any Anthropic-API client to Amazon Bedrock.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
            environment:
              {ENV_MAIN}        Main Bedrock model ID (used if --model is omitted).
              {ENV_LIGHT}  Optional light/background model ID (used if --model-light is omitted).
              AWS_REGION, AWS_PROFILE, etc.       Standard boto3 credential / region chain.

            examples:
              # Just run the proxy; wire your own client.
              bedrock-bridge --model moonshotai.kimi-k2.5

              # Or pull config from env.
              export {ENV_MAIN}=moonshotai.kimi-k2.5
              export {ENV_LIGHT}=anthropic.claude-haiku-4-5-20251001-v1:0
              bedrock-bridge

              # Launch Claude Code through the proxy.
              bedrock-bridge --model moonshotai.kimi-k2.5 --claude

              # Pass extra flags through to claude (only valid with --claude).
              bedrock-bridge --model moonshotai.kimi-k2.5 --claude -- --verbose
        """),
    )
    p.add_argument("--model", "-m", help=f"Main Bedrock model ID. Falls back to ${ENV_MAIN}.")
    p.add_argument("--model-light", help=f"Optional light-model ID. Falls back to ${ENV_LIGHT}.")
    p.add_argument("--region", "-r", help="AWS region (overrides boto3 chain).")
    p.add_argument(
        "--claude",
        action="store_true",
        help="Spawn the `claude` CLI wired to this proxy. Without this flag, the proxy just runs.",
    )
    p.add_argument("--print", help="With --claude: forward to `claude --print`.")
    return p


def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] in ("--version", "-V"):
        print(f"bedrock-bridge {__version__}")
        return

    args, passthrough = _build_launch_parser("bedrock-bridge").parse_known_args(argv)
    args.passthrough = passthrough

    if passthrough and not args.claude:
        _fatal("extra args are only forwarded with --claude. Drop them or add --claude.")
    if args.print and not args.claude:
        _fatal("--print is only valid with --claude.")

    cmd_launch(args)


if __name__ == "__main__":
    main()
