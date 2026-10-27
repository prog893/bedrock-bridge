"""Context window per Bedrock model, from the AWS model cards.

Claude Code assumes a 200K window for a model ID it does not recognize, which
is every model the bridge serves. Too small (GLM 5.3 has 1M) and it compacts
early; too large (gpt-oss has 128K) and it compacts only after Bedrock rejects
the request. The CLI passes the main model's window to Claude Code as
CLAUDE_CODE_MAX_CONTEXT_TOKENS.

Source: the "Context window" line of each model card under
https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html, swept
2026-10-15. Keys are bedrock-runtime base model IDs; inference-profile
prefixes (global., us., ...) are stripped before lookup. Models listed only on
bedrock-mantle are left out, as is mistral.mistral-large-2407-v1:0 (no
documented window).
"""

from __future__ import annotations

from .translate import _PROFILE_PREFIX

CONTEXT_WINDOWS: dict[str, int] = {
    "ai21.jamba-1-5-large-v1:0": 256_000,
    "ai21.jamba-1-5-mini-v1:0": 256_000,
    "amazon.nova-2-lite-v1:0": 1_000_000,
    "amazon.nova-2-sonic-v1:0": 1_000_000,
    "amazon.nova-lite-v1:0": 300_000,
    "amazon.nova-micro-v1:0": 128_000,
    "amazon.nova-pro-v1:0": 300_000,
    "cohere.command-r-plus-v1:0": 128_000,
    "cohere.command-r-v1:0": 128_000,
    "deepseek.r1-v1:0": 128_000,
    "deepseek.v3-v1:0": 128_000,
    "deepseek.v3.2": 164_000,
    "google.gemma-3-12b-it": 128_000,
    "google.gemma-3-27b-it": 128_000,
    "google.gemma-3-4b-it": 128_000,
    "meta.llama3-1-405b-instruct-v1:0": 128_000,
    "meta.llama3-1-70b-instruct-v1:0": 128_000,
    "meta.llama3-1-8b-instruct-v1:0": 128_000,
    "meta.llama3-2-11b-instruct-v1:0": 128_000,
    "meta.llama3-2-1b-instruct-v1:0": 128_000,
    "meta.llama3-2-3b-instruct-v1:0": 128_000,
    "meta.llama3-2-90b-instruct-v1:0": 128_000,
    "meta.llama3-3-70b-instruct-v1:0": 128_000,
    "meta.llama3-70b-instruct-v1:0": 8_000,
    "meta.llama3-8b-instruct-v1:0": 8_000,
    "meta.llama4-maverick-17b-instruct-v1:0": 1_000_000,
    "meta.llama4-scout-17b-instruct-v1:0": 10_000_000,
    "minimax.minimax-m2": 1_000_000,
    "minimax.minimax-m2.1": 196_000,
    "minimax.minimax-m2.5": 196_000,
    "mistral.devstral-2-123b": 256_000,
    "mistral.magistral-small-2509": 128_000,
    "mistral.ministral-3-14b-instruct": 128_000,
    "mistral.ministral-3-3b-instruct": 128_000,
    "mistral.ministral-3-8b-instruct": 128_000,
    "mistral.mistral-7b-instruct-v0:2": 32_000,
    "mistral.mistral-large-2402-v1:0": 32_000,
    "mistral.mistral-large-3-675b-instruct": 256_000,
    "mistral.mistral-small-2402-v1:0": 32_000,
    "mistral.mixtral-8x7b-instruct-v0:1": 32_000,
    "mistral.pixtral-large-2502-v1:0": 128_000,
    "mistral.voxtral-mini-3b-2507": 32_000,
    "mistral.voxtral-small-24b-2507": 32_000,
    "moonshot.kimi-k2-thinking": 256_000,
    "moonshotai.kimi-k2.5": 256_000,
    "moonshotai.kimi-k3": 1_000_000,
    "nvidia.nemotron-nano-12b-v2": 128_000,
    "nvidia.nemotron-nano-3-30b": 256_000,
    "nvidia.nemotron-nano-9b-v2": 128_000,
    "nvidia.nemotron-super-3-120b": 256_000,
    "openai.gpt-5.4": 1_050_000,
    "openai.gpt-5.5": 1_050_000,
    "openai.gpt-5.6-luna": 1_050_000,
    "openai.gpt-5.6-sol": 1_050_000,
    "openai.gpt-5.6-terra": 1_050_000,
    "openai.gpt-6-astra": 1_050_000,
    "openai.gpt-6-luna": 1_050_000,
    "openai.gpt-6-sol": 1_050_000,
    "openai.gpt-6.1-sol": 1_000_000,
    "openai.gpt-oss-120b-1:0": 128_000,
    "openai.gpt-oss-20b-1:0": 128_000,
    "openai.gpt-oss-safeguard-120b": 128_000,
    "openai.gpt-oss-safeguard-20b": 128_000,
    "qwen.qwen3-235b-a22b-2507-v1:0": 256_000,
    "qwen.qwen3-32b-v1:0": 32_000,
    "qwen.qwen3-coder-30b-a3b-v1:0": 256_000,
    "qwen.qwen3-coder-480b-a35b-v1:0": 128_000,
    "qwen.qwen3-coder-next": 256_000,
    "qwen.qwen3-next-80b-a3b": 256_000,
    "qwen.qwen3-vl-235b-a22b": 256_000,
    "writer.palmyra-vision-7b": 4_000,
    "writer.palmyra-x4-v1:0": 128_000,
    "writer.palmyra-x5-v1:0": 128_000,
    "xai.grok-4.6": 500_000,
    "xai.grok-4.7": 500_000,
    "zai.glm-4.7": 203_000,
    "zai.glm-4.7-flash": 203_000,
    "zai.glm-5": 200_000,
    "zai.glm-5.3": 1_000_000,
}


def context_window(model_id: str) -> int | None:
    """Documented context window for a Bedrock model or inference profile ID."""
    return CONTEXT_WINDOWS.get(_PROFILE_PREFIX.sub("", model_id))
