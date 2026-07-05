"""Provider-agnostic LLM client with tool-calling support.

Accepts messages in OpenAI canonical format and returns a normalised
LLMResponse. All provider-specific wiring (Anthropic message structure,
tool-result format, content blocks) is handled here so that the planner
never needs to know which provider is active.

Supported providers (Section 6.2): "openai", "anthropic"
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.config import Config
from agent.tool_spec import to_anthropic_tools

logger = logging.getLogger(__name__)


# ── normalised data structures ────────────────────────────────────────────────

@dataclass
class ToolCall:
    """One tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]   # already-parsed dict (not a JSON string)


@dataclass
class LLMResponse:
    """Normalised response returned by either provider."""
    text: Optional[str]             # final answer text when the LLM is done
    tool_calls: List[ToolCall]      # non-empty when the LLM wants tool results
    raw_message: Dict[str, Any]     # serialisable assistant turn for history
    finish_reason: str              # "stop" | "tool_calls" | "length" | …


# ── client ────────────────────────────────────────────────────────────────────

class LLMClient:
    """Thin wrapper over the OpenAI and Anthropic Python SDKs.

    Args:
        config:  Parsed Config with provider credentials and generation settings.
        tools:   Tool list in OpenAI canonical format (converted internally for Anthropic).
    """

    def __init__(self, config: Config, tools: List[Dict[str, Any]]) -> None:
        self._config = config
        self._tools = tools
        self._provider = config.provider.lower()
        # Running token usage across all API calls made by this client.
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.api_calls = 0

        if self._provider == "openai":
            from openai import OpenAI  # type: ignore
            self._openai_client = OpenAI(api_key=config.openai.api_key)
        elif self._provider == "anthropic":
            from anthropic import Anthropic  # type: ignore
            self._anthropic_client = Anthropic(api_key=config.anthropic.api_key)
        else:
            raise ValueError(
                f"Unknown provider '{config.provider}'. Expected 'openai' or 'anthropic'."
            )

    def _record_usage(self, usage) -> None:
        """Accumulate token usage from a provider response (OpenAI or Anthropic)."""
        self.api_calls += 1
        if not usage:
            return
        p = getattr(usage, "prompt_tokens", None)
        if p is None:
            p = getattr(usage, "input_tokens", 0)
        c = getattr(usage, "completion_tokens", None)
        if c is None:
            c = getattr(usage, "output_tokens", 0)
        self.prompt_tokens += p or 0
        self.completion_tokens += c or 0
        self.total_tokens += getattr(usage, "total_tokens", (p or 0) + (c or 0))

    # ------------------------------------------------------------------ public

    # Transient provider hiccups (rate limit, overloaded, brief network faults)
    # must not lose a contest turn: retry with backoff before giving up.
    # Fatal errors (bad key, no quota) re-raise immediately — retrying is useless.
    _RETRY_DELAYS_S = (2, 8, 20)
    _FATAL_MARKERS = ("insufficient_quota", "incorrect api key", "invalid x-api-key",
                      "authentication", "permission")

    def chat(self, messages: List[Dict[str, Any]]) -> LLMResponse:
        """Send *messages* to the configured LLM and return a normalised response.

        *messages* follow OpenAI format:
            {"role": "system"|"user"|"assistant"|"tool", "content": …, …}
        """
        last_exc: Exception | None = None
        for attempt, delay in enumerate((0,) + self._RETRY_DELAYS_S):
            if delay:
                logger.warning("LLM transient error (%s) — retry %d in %ds",
                               last_exc, attempt, delay)
                time.sleep(delay)
            try:
                if self._provider == "openai":
                    return self._chat_openai(messages)
                return self._chat_anthropic(messages)
            except Exception as exc:  # noqa: BLE001
                text = str(exc).lower()
                if any(m in text for m in self._FATAL_MARKERS):
                    raise
                last_exc = exc
        raise last_exc  # transient retries exhausted

    # ----------------------------------------------------------------- OpenAI

    def _chat_openai(self, messages: List[Dict[str, Any]]) -> LLMResponse:
        cfg = self._config
        logger.debug("--- [OpenAI] Sending request with %d messages ---", len(messages))
        response = self._openai_client.chat.completions.create(
            model=cfg.openai.model,
            messages=messages,
            tools=self._tools,
            tool_choice="auto",
            temperature=cfg.generation.temperature,
            max_tokens=cfg.generation.max_output_tokens,
        )
        self._record_usage(getattr(response, "usage", None))

        choice = response.choices[0]
        msg = choice.message
        finish = choice.finish_reason or "stop"

        # Build a serialisable raw_message for the conversation history.
        raw: Dict[str, Any] = {"role": "assistant", "content": msg.content}

        if msg.content:
            logger.debug("\n=== [OpenAI Thought] ===\n%s\n========================", msg.content)

        if finish == "tool_calls" and msg.tool_calls:
            for tc in msg.tool_calls:
                logger.debug("=== [OpenAI ToolCall] ===\nName: %s\nArgs: %s\n=========================", tc.function.name, tc.function.arguments)
            raw["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=self._parse_json(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]
            return LLMResponse(
                text=None,
                tool_calls=tool_calls,
                raw_message=raw,
                finish_reason="tool_calls",
            )

        return LLMResponse(
            text=msg.content or "",
            tool_calls=[],
            raw_message=raw,
            finish_reason=finish,
        )

    # --------------------------------------------------------------- Anthropic

    def _chat_anthropic(self, messages: List[Dict[str, Any]]) -> LLMResponse:
        cfg = self._config

        # Extract system message from the list (Anthropic takes it separately).
        system_text = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
                break

        anthropic_msgs = self._to_anthropic_messages(messages)
        anthropic_tools = to_anthropic_tools(self._tools)

        kwargs: Dict[str, Any] = dict(
            model=cfg.anthropic.model,
            max_tokens=cfg.generation.max_output_tokens,
            messages=anthropic_msgs,
            tools=anthropic_tools,
            temperature=cfg.generation.temperature,
        )
        if system_text:
            kwargs["system"] = system_text

        logger.debug("--- [Anthropic] Sending request with %d messages ---", len(anthropic_msgs))
        response = self._anthropic_client.messages.create(**kwargs)
        self._record_usage(getattr(response, "usage", None))

        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        raw_blocks: List[Dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                logger.debug("\n=== [Anthropic Thought] ===\n%s\n===========================", block.text)
                text_parts.append(block.text)
                raw_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                logger.debug("=== [Anthropic ToolCall] ===\nName: %s\nArgs: %s\n============================", block.name, block.input)
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )
                raw_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        raw_message: Dict[str, Any] = {"role": "assistant", "content": raw_blocks}
        finish = response.stop_reason or "end_turn"  # "end_turn" | "tool_use" | "max_tokens"

        if tool_calls:
            return LLMResponse(
                text=None,
                tool_calls=tool_calls,
                raw_message=raw_message,
                finish_reason="tool_calls",
            )

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=[],
            raw_message=raw_message,
            finish_reason=finish,
        )

    def _to_anthropic_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-style message history to Anthropic format.

        Key differences:
        - "system" role messages are omitted (passed as the `system` param).
        - "assistant" messages that contain tool_calls become content-block lists.
        - "tool" role messages are merged into a single "user" message with
          tool_result content blocks (Anthropic requires alternating roles).
        """
        result: List[Dict[str, Any]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")

            if role == "system":
                i += 1
                continue

            if role == "user":
                content = msg.get("content", "")
                result.append({"role": "user", "content": content})
                i += 1

            elif role == "assistant":
                if msg.get("tool_calls"):
                    # Convert tool_calls to Anthropic content blocks.
                    blocks: List[Dict[str, Any]] = []
                    if msg.get("content"):
                        blocks.append({"type": "text", "text": msg["content"]})
                    for tc in msg["tool_calls"]:
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": self._parse_json(tc["function"]["arguments"]),
                            }
                        )
                    result.append({"role": "assistant", "content": blocks})
                elif isinstance(msg.get("content"), list):
                    # Already in Anthropic block format (from a previous round-trip).
                    result.append({"role": "assistant", "content": msg["content"]})
                else:
                    result.append(
                        {"role": "assistant", "content": msg.get("content", "")}
                    )
                i += 1

            elif role == "tool":
                # Collect all consecutive "tool" messages into one user turn.
                tool_blocks: List[Dict[str, Any]] = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tm = messages[i]
                    tool_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tm["tool_call_id"],
                            "content": tm.get("content", ""),
                        }
                    )
                    i += 1
                result.append({"role": "user", "content": tool_blocks})

            else:
                i += 1

        return result

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _parse_json(value: Any) -> Dict[str, Any]:
        """Parse a JSON string into a dict; return {} on any error."""
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse tool arguments: %r", value)
            return {}
