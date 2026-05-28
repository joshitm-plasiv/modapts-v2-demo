"""
Module 1 — LLM Adapter

Provider-agnostic adapter. Single function interface:
    call_llm(system_prompt, user_message) → raw_response

Provider detected from MODAPTS_LLM_PROVIDER env var.
Supported: anthropic, openai, mistral, ollama.

Raises AdapterError on configuration or API failures.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional


class AdapterError(Exception):
    """Base exception for adapter failures."""
    pass


class AdapterConfigError(AdapterError):
    """Missing or invalid configuration (env vars)."""
    pass


class AdapterAPIError(AdapterError):
    """API call failed after retries."""
    pass


@dataclass
class AdapterConfig:
    provider: str
    model: str
    api_key: Optional[str]

    @classmethod
    def from_env(cls) -> "AdapterConfig":
        provider = os.environ.get("MODAPTS_LLM_PROVIDER", "").strip().lower()
        model = os.environ.get("MODAPTS_LLM_MODEL", "").strip()
        api_key = os.environ.get("MODAPTS_API_KEY", "").strip() or None

        if not provider:
            raise AdapterConfigError(
                "MODAPTS_LLM_PROVIDER env var is required. "
                "Supported: anthropic, openai, mistral, ollama"
            )
        if not model:
            raise AdapterConfigError(
                "MODAPTS_LLM_MODEL env var is required. "
                "Example: claude-sonnet-4-20250514, gpt-4o, mistral-large-latest"
            )
        if provider in ("anthropic", "openai", "mistral") and not api_key:
            raise AdapterConfigError(
                f"MODAPTS_API_KEY env var is required for provider '{provider}'"
            )

        return cls(provider=provider, model=model, api_key=api_key)


def call_llm(system_prompt: str, user_message: str, config: Optional[AdapterConfig] = None) -> str:
    """
    Send a system prompt + user message to the configured LLM.
    Returns the raw response string.

    Raises:
        AdapterConfigError: missing/invalid env vars
        AdapterAPIError: API call failed
    """
    if config is None:
        config = AdapterConfig.from_env()

    dispatch = {
        "anthropic": _call_anthropic,
        "openai": _call_openai,
        "mistral": _call_mistral,
        "ollama": _call_ollama,
    }

    handler = dispatch.get(config.provider)
    if handler is None:
        raise AdapterConfigError(
            f"Unsupported provider '{config.provider}'. "
            f"Supported: {', '.join(dispatch.keys())}"
        )

    return handler(system_prompt, user_message, config)


def _call_anthropic(system_prompt: str, user_message: str, config: AdapterConfig) -> str:
    try:
        import anthropic
    except ImportError:
        raise AdapterError("anthropic package not installed. Run: pip install anthropic")

    try:
        client = anthropic.Anthropic(api_key=config.api_key)
        response = client.messages.create(
            model=config.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except anthropic.APIError as e:
        raise AdapterAPIError(f"Anthropic API error: {e}")
    except Exception as e:
        raise AdapterAPIError(f"Anthropic call failed: {e}")


def _call_openai(system_prompt: str, user_message: str, config: AdapterConfig) -> str:
    try:
        import openai
    except ImportError:
        raise AdapterError("openai package not installed. Run: pip install openai")

    try:
        client = openai.OpenAI(api_key=config.api_key)
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content
    except openai.APIError as e:
        raise AdapterAPIError(f"OpenAI API error: {e}")
    except Exception as e:
        raise AdapterAPIError(f"OpenAI call failed: {e}")


def _call_mistral(system_prompt: str, user_message: str, config: AdapterConfig) -> str:
    try:
        from mistralai import Mistral
    except ImportError:
        raise AdapterError("mistralai package not installed. Run: pip install mistralai")

    try:
        client = Mistral(api_key=config.api_key)
        response = client.chat.complete(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        raise AdapterAPIError(f"Mistral call failed: {e}")


def _call_ollama(system_prompt: str, user_message: str, config: AdapterConfig) -> str:
    """Ollama via its OpenAI-compatible endpoint. No API key needed."""
    import urllib.request
    import urllib.error

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    url = f"{base_url}/v1/chat/completions"

    payload = json.dumps({
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise AdapterAPIError(f"Ollama call failed: {e}")
    except (KeyError, IndexError) as e:
        raise AdapterAPIError(f"Unexpected Ollama response format: {e}")
