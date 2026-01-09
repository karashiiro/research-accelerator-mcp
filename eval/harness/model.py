"""
Custom Strands model provider for z.ai API.

Calls z.ai's Anthropic-compatible API with API key authentication.
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx
from strands.models import Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

logger = logging.getLogger(__name__)


# API Configuration
MESSAGES_ENDPOINT = "/v1/messages"

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ZAIModel(Model):
    """
    Strands model provider for z.ai's Anthropic-compatible API.

    Uses API key authentication to call z.ai's GLM models via their
    Anthropic-compatible endpoint.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.z.ai/api/anthropic",
        model_id: str = "GLM-4.7",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")  # Remove trailing slash if present
        self._config = {
            "model_id": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

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

        Not implemented for ZAIModel - use stream() instead.
        """
        raise NotImplementedError(
            "structured_output is not implemented for ZAIModel. "
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
        Stream responses from z.ai API.

        Converts Anthropic-format SSE events to Strands StreamEvent format.
        Includes automatic retry with exponential backoff for transient errors.
        """
        logger.debug(f"stream() called with {len(messages)} messages")

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
            # z.ai accepts system prompt as a simple string or content blocks
            payload["system"] = system_prompt

        if tool_specs:
            payload["tools"] = self._convert_tools(tool_specs)

        msg_count = len(payload['messages'])
        logger.debug(f"Request payload: model={payload['model']}, messages={msg_count}")

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
        # Build headers for z.ai API
        headers = {
            # Auth - z.ai uses x-api-key header
            "x-api-key": self._api_key,
            # Content
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Anthropic API version (z.ai is Anthropic-compatible)
            "anthropic-version": "2023-06-01",
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
                f"{self._base_url}{MESSAGES_ENDPOINT}",
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
                        # Note: z.ai reports input_tokens=0 here; actual value comes in message_delta

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

                        # Track tokens from message_delta (z.ai reports final counts here)
                        usage = event.get("usage", {})
                        # z.ai returns input_tokens in message_delta, not message_start
                        if "input_tokens" in usage:
                            input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        logger.debug(
                            f"message_delta usage: input_tokens={input_tokens}, "
                            f"output_tokens={output_tokens}"
                        )

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
            block_count = len(content) if isinstance(content, list) else 'N/A'
            logger.debug(f"Converting message {i}: role={role}, content_blocks={block_count}")

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
            type_name = type(block).__name__
            logger.warning(f"Message {msg_idx} block {block_idx}: unexpected type {type_name}")
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
