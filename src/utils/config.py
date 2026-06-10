"""Configuration loader for the CADA EDA system.

Reads a YAML file conforming to the contest specification (Section 6.2).
API keys may be given literally or as ${ENV_VAR} placeholders — the loader
expands them from environment variables, preferring a local .env file.

Example YAML:
    provider: "openai"
    openai:
      api_key: "${OPENAI_API_KEY}"
      model: "gpt-4o-mini"
    anthropic:
      api_key: "${ANTHROPIC_API_KEY}"
      model: "claude-haiku-4-5"
    generation:
      temperature: 0.2
      max_output_tokens: 4096
"""

import os
import re
import yaml
from dataclasses import dataclass
from pathlib import Path

from utils.paths import PROJECT_ROOT

# Load .env from the project root (silently ignored if absent or dotenv missing)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass  # python-dotenv not installed — fall back to real env vars only

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _expand(value: str) -> str:
    """Replace ${VAR} tokens in *value* with environment variable values."""
    def _sub(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))  # keep token if var missing
    return _ENV_RE.sub(_sub, value)


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o-mini"


@dataclass
class AnthropicConfig:
    api_key: str
    model: str = "claude-haiku-4-5"


@dataclass
class GenerationConfig:
    temperature: float = 0.2
    max_output_tokens: int = 4096


@dataclass
class Config:
    provider: str           # "openai" | "anthropic"
    openai: OpenAIConfig
    anthropic: AnthropicConfig
    generation: GenerationConfig

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Parse a YAML config file and return a Config instance.

        ${ENV_VAR} placeholders in string values are expanded from the
        environment (populated from .env if present).
        """
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        provider = _expand(data.get("provider", "openai")).strip().lower()

        oa = data.get("openai", {})
        openai_cfg = OpenAIConfig(
            api_key=_expand(oa.get("api_key", "")),
            model=_expand(oa.get("model", "gpt-4o-mini")),
        )

        an = data.get("anthropic", {})
        anthropic_cfg = AnthropicConfig(
            api_key=_expand(an.get("api_key", "")),
            model=_expand(an.get("model", "claude-haiku-4-5")),
        )

        gen = data.get("generation", {})
        generation_cfg = GenerationConfig(
            temperature=float(gen.get("temperature", 0.2)),
            max_output_tokens=int(gen.get("max_output_tokens", 4096)),
        )

        return cls(
            provider=provider,
            openai=openai_cfg,
            anthropic=anthropic_cfg,
            generation=generation_cfg,
        )
