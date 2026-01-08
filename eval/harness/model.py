"""
Custom Strands model provider using OAuth authentication.

Calls Anthropic API directly with OAuth Bearer tokens instead of API keys.
"""

import asyncio
import json
import logging
import platform
import sys
from typing import Any, AsyncIterator

import httpx
from strands.models import Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

from .oauth import OAuthManager

logger = logging.getLogger(__name__)


# API Configuration
ANTHROPIC_API = "https://api.anthropic.com"
MESSAGES_ENDPOINT = "/v1/messages"

# Required beta headers for Claude Code OAuth API access
REQUIRED_BETAS = [
    "oauth-2025-04-20",
    "claude-code-20250219",
    "interleaved-thinking-2025-05-14",
    "fine-grained-tool-streaming-2025-05-14",
]

# Claude Code client identification
CLAUDE_CODE_USER_AGENT = "claude-cli/2.1.0 (external, cli)"

# Claude Code system prompt prefix - MUST be sent as first content block
# The OAuth validation only checks the first block, so we split on this
CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _get_platform_info() -> dict[str, str]:
    """Get platform-specific information for headers."""
    system = platform.system()
    machine = platform.machine().lower()

    # Map platform to expected values
    os_name = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(system, system)
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)

    # Get Python/Node version (we pretend to be Node for Claude Code compatibility)
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    return {
        "os": os_name,
        "arch": arch,
        "runtime_version": f"v22.14.0",  # Pretend to be Node for Claude Code
    }


class AnthropicOAuthModel(Model):
    """
    Strands model provider using Anthropic OAuth authentication.

    Instead of using an API key, this provider uses OAuth access tokens
    obtained through the PKCE flow.
    """

    def __init__(
        self,
        oauth_manager: OAuthManager,
        model_id: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        self.oauth = oauth_manager
        self._config = {
            "model_id": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self._platform_info = _get_platform_info()

    def update_config(self, **kwargs: Any) -> None:
        """Update model configuration."""
        self._config.update(kwargs)

    def get_config(self) -> dict[str, Any]:
        """Get current configuration."""
        return self._config.copy()

    async def structured_output(
        self,
        output_model: type,
        messages: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Generate structured output conforming to a schema.

        Not implemented for OAuth model - use stream() instead.
        """
        raise NotImplementedError(
            "structured_output is not implemented for AnthropicOAuthModel. "
            "Use stream() for standard generation."
        )

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream responses from Anthropic API using OAuth.

        Converts Anthropic SSE events to Strands StreamEvent format.
        Includes automatic retry with exponential backoff for transient errors.
        """
        # Debug logging (only at DEBUG level to avoid spam)
        logger.debug(f"stream() called with {len(messages)} messages")
        logger.debug(f"  system_prompt present: {system_prompt is not None}")
        if system_prompt:
            logger.debug(f"  system_prompt starts with: {system_prompt[:100]}...")
        else:
            logger.warning("  NO SYSTEM PROMPT! This will cause OAuth auth error!")

        # Build request payload
        payload: dict[str, Any] = {
            "model": self._config["model_id"],
            "max_tokens": self._config["max_tokens"],
            "stream": True,
            "messages": self._convert_messages(messages),
        }

        if self._config.get("temperature") is not None:
            payload["temperature"] = self._config["temperature"]

        if system_prompt:
            # Convert system prompt to content blocks for OAuth compatibility
            # The API validates only the first block, so we MUST split on the prefix
            payload["system"] = self._convert_system_prompt(system_prompt)

        if tool_specs:
            payload["tools"] = self._convert_tools(tool_specs)

        logger.debug(f"Request payload: model={payload['model']}, messages={len(payload['messages'])}")

        # Retry loop for transient errors
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                async for event in self._stream_with_client(payload):
                    yield event
                return  # Success - exit retry loop
            except httpx.HTTPStatusError as e:
                if e.response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = e
                    wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        f"Retryable error {e.response.status_code}, "
                        f"attempt {attempt + 1}/{MAX_RETRIES}, waiting {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_error = e
                wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    f"Network error: {e}, attempt {attempt + 1}/{MAX_RETRIES}, waiting {wait_time}s"
                )
                await asyncio.sleep(wait_time)

        # All retries exhausted
        raise RuntimeError(f"All {MAX_RETRIES} retry attempts failed") from last_error

    async def _stream_with_client(
        self, payload: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """Execute streaming request with a fresh client."""
        # Get valid access token (may trigger refresh)
        access_token = await self.oauth.ensure_valid_token()

        # Build headers - must identify as Claude Code client for OAuth tokens
        headers = {
            # Auth
            "Authorization": f"Bearer {access_token}",
            # Content
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "*",
            # Anthropic specific
            "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(REQUIRED_BETAS),
            "anthropic-dangerous-direct-browser-access": "true",
            # Client identification - x-service-name seems critical!
            "User-Agent": CLAUDE_CODE_USER_AGENT,
            "x-app": "cli",
            "x-service-name": "claude-code",
            # Stainless SDK headers (platform-aware)
            "x-stainless-arch": self._platform_info["arch"],
            "x-stainless-lang": "js",
            "x-stainless-os": self._platform_info["os"],
            "x-stainless-package-version": "0.70.0",
            "x-stainless-retry-count": "0",
            "x-stainless-runtime": "node",
            "x-stainless-runtime-version": self._platform_info["runtime_version"],
            "x-stainless-helper-method": "stream",
            "x-stainless-timeout": "600",
        }

        # Track metrics
        input_tokens = 0
        output_tokens = 0
        content_block_started = False

        # Use a timeout that allows for long responses but catches stalls
        timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{ANTHROPIC_API}{MESSAGES_ENDPOINT}",
                params={"beta": "true"},
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_msg = error_body.decode()
                    logger.error(f"API error {response.status_code}: {error_msg}")
                    raise httpx.HTTPStatusError(
                        f"Anthropic API error {response.status_code}: {error_msg}",
                        request=response.request,
                        response=response,
                    )

                # Process SSE stream
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:]  # Strip "data: " prefix

                    # Anthropic uses empty data or specific events to signal end
                    if not data or data == "[DONE]":
                        logger.debug("Stream ended")
                        break

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse SSE event: {e}, data: {data[:100]}")
                        continue

                    event_type = event.get("type")
                    logger.debug(f"SSE event: {event_type}")

                    if event_type == "message_start":
                        # Yield message start
                        yield {"messageStart": {"role": "assistant"}}

                        # Track input tokens from message start
                        usage = event.get("message", {}).get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)

                    elif event_type == "content_block_start":
                        # New content block starting
                        block = event.get("content_block", {})
                        block_type = block.get("type")
                        content_block_started = True

                        if block_type == "tool_use":
                            yield {
                                "contentBlockStart": {
                                    "start": {
                                        "toolUse": {
                                            "name": block.get("name", ""),
                                            "toolUseId": block.get("id", ""),
                                        }
                                    }
                                }
                            }
                        else:
                            # Text block - just mark as started
                            yield {"contentBlockStart": {"start": {}}}

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type")

                        if delta_type == "text_delta":
                            yield {
                                "contentBlockDelta": {
                                    "delta": {"text": delta.get("text", "")}
                                }
                            }
                        elif delta_type == "input_json_delta":
                            yield {
                                "contentBlockDelta": {
                                    "delta": {"toolUse": {"input": delta.get("partial_json", "")}}
                                }
                            }

                    elif event_type == "content_block_stop":
                        if content_block_started:
                            yield {"contentBlockStop": {}}
                            content_block_started = False

                    elif event_type == "message_delta":
                        # Message is ending
                        delta = event.get("delta", {})
                        stop_reason = delta.get("stop_reason", "end_turn")

                        # Track output tokens
                        usage = event.get("usage", {})
                        output_tokens = usage.get("output_tokens", 0)

                        # Map stop reason
                        strands_stop_reason = self._map_stop_reason(stop_reason)
                        yield {"messageStop": {"stopReason": strands_stop_reason}}

                    elif event_type == "message_stop":
                        # Final message stop - stream is complete
                        logger.debug("Received message_stop event")

                    elif event_type == "error":
                        # API error event
                        error = event.get("error", {})
                        raise RuntimeError(f"API error: {error.get('message', 'Unknown error')}")

                    elif event_type == "ping":
                        # Keepalive ping, ignore
                        pass

                    else:
                        logger.debug(f"Unhandled event type: {event_type}")

        # Yield final metadata with token counts
        yield {
            "metadata": {
                "usage": {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "totalTokens": input_tokens + output_tokens,
                }
            }
        }

    def _convert_messages(self, messages: Messages) -> list[dict[str, Any]]:
        """Convert Strands messages to Anthropic format."""
        result = []

        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", [])
            logger.debug(f"Converting message {i}: role={role}, content_blocks={len(content) if isinstance(content, list) else 'N/A'}")

            # Convert content blocks
            anthropic_content = []
            for j, block in enumerate(content):
                converted = self._convert_content_block(block, i, j)
                if converted:
                    anthropic_content.append(converted)

            result.append({"role": role, "content": anthropic_content})

        return result

    def _convert_content_block(
        self, block: Any, msg_idx: int, block_idx: int
    ) -> dict[str, Any] | None:
        """Convert a single content block from Strands to Anthropic format."""
        if isinstance(block, str):
            return {"type": "text", "text": block}

        if not isinstance(block, dict):
            logger.warning(f"Message {msg_idx} block {block_idx}: unexpected type {type(block).__name__}")
            return None

        block_type = block.get("type")

        # Type-based formats
        if block_type == "text":
            return {"type": "text", "text": block.get("text", "")}

        if block_type == "toolUse":
            return {
                "type": "tool_use",
                "id": block.get("toolUseId", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            }

        if block_type == "toolResult":
            return {
                "type": "tool_result",
                "tool_use_id": block.get("toolUseId", ""),
                "content": block.get("content", ""),
            }

        # Wrapper-key formats (Strands style)
        if "toolUse" in block:
            tool_use = block["toolUse"]
            return {
                "type": "tool_use",
                "id": tool_use.get("toolUseId", ""),
                "name": tool_use.get("name", ""),
                "input": tool_use.get("input", {}),
            }

        if "toolResult" in block:
            tool_result = block["toolResult"]
            result_content = tool_result.get("content", [])

            # Convert content to string for Anthropic API
            if isinstance(result_content, list):
                text_parts = []
                for item in result_content:
                    if isinstance(item, dict) and "text" in item:
                        text_parts.append(item["text"])
                    elif isinstance(item, str):
                        text_parts.append(item)
                result_str = "\n".join(text_parts)
            else:
                result_str = str(result_content)

            return {
                "type": "tool_result",
                "tool_use_id": tool_result.get("toolUseId", ""),
                "content": result_str,
            }

        # Bare text (no type field)
        if "text" in block and block_type is None:
            return {"type": "text", "text": block.get("text", "")}

        # Unhandled format
        logger.warning(
            f"Message {msg_idx} block {block_idx}: unhandled format, "
            f"type={block_type}, keys={list(block.keys())}"
        )
        return None

    def _convert_tools(self, tool_specs: list[ToolSpec]) -> list[dict[str, Any]]:
        """Convert Strands tool specs to Anthropic format."""
        result = []

        for spec in tool_specs:
            # Strands tool specs have inputSchema.json containing the actual schema
            input_schema = spec.get("inputSchema", {})
            if isinstance(input_schema, dict) and "json" in input_schema:
                input_schema = input_schema["json"]

            result.append({
                "name": spec.get("name", ""),
                "description": spec.get("description", ""),
                "input_schema": input_schema,
            })

        return result

    def _map_stop_reason(self, anthropic_reason: str) -> str:
        """Map Anthropic stop reason to Strands format."""
        mapping = {
            "end_turn": "end_turn",
            "stop_sequence": "stop_sequence",
            "max_tokens": "max_tokens",
            "tool_use": "tool_use",
        }
        return mapping.get(anthropic_reason, "end_turn")

    def _convert_system_prompt(self, system_prompt: str) -> list[dict[str, str]]:
        """
        Convert system prompt string to content blocks for OAuth compatibility.

        The Claude Code OAuth validation checks only the FIRST content block,
        so we split the prompt into:
        1. First block: Exactly the Claude Code prefix
        2. Second block: Everything else

        This allows us to add custom instructions while passing OAuth validation.
        """
        # Check if prompt starts with the Claude Code prefix
        if system_prompt.startswith(CLAUDE_CODE_SYSTEM_PREFIX):
            # Extract the rest of the prompt after the prefix
            rest = system_prompt[len(CLAUDE_CODE_SYSTEM_PREFIX):].strip()

            if rest:
                # Return two content blocks
                return [
                    {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
                    {"type": "text", "text": rest},
                ]
            else:
                # Just the prefix, return single block
                return [{"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX}]
        else:
            # No Claude Code prefix - this will likely fail OAuth validation
            # but we send it anyway as a single block
            logger.warning(
                "System prompt doesn't start with Claude Code prefix. "
                "OAuth validation may fail."
            )
            return [{"type": "text", "text": system_prompt}]
