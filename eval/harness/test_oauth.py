"""Quick test script to isolate OAuth + Agent issue."""
import asyncio

from strands import Agent

from .config import get_config
from .model import AnthropicOAuthModel
from .oauth import get_or_create_oauth


async def test_direct_no_tools():
    """Test 1: Direct model.stream() WITHOUT tools."""
    print("\n=== TEST 1: Direct model.stream() WITHOUT tools ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    test_messages = [{
        "role": "user",
        "content": [{"type": "text", "text": "Say 'test1' and nothing else."}],
    }]
    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude."

    try:
        response_text = ""
        async for event in model.stream(test_messages, system_prompt=system_prompt):
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    response_text += delta["text"]
        print(f"SUCCESS! Response: {response_text.strip()}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_direct_with_tools():
    """Test 2: Direct model.stream() WITH tools."""
    print("\n=== TEST 2: Direct model.stream() WITH tools ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    test_messages = [{
        "role": "user",
        "content": [{"type": "text", "text": "Say 'test2' and nothing else."}],
    }]
    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude."

    # Simple test tool
    tool_specs = [{
        "name": "test_tool",
        "description": "A test tool",
        "inputSchema": {"json": {"type": "object", "properties": {}}},
    }]

    try:
        response_text = ""
        stream = model.stream(
            test_messages, tool_specs=tool_specs, system_prompt=system_prompt
        )
        async for event in stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    response_text += delta["text"]
        print(f"SUCCESS! Response: {response_text.strip()}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_agent_no_tools():
    """Test 3: Agent WITHOUT tools."""
    print("\n=== TEST 3: Strands Agent WITHOUT tools ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude."

    try:
        agent = Agent(
            model=model,
            tools=[],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test3' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_agent_with_tools():
    """Test 4: Agent WITH tools."""
    print("\n=== TEST 4: Strands Agent WITH tools ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude."

    # Import tavily
    from strands_tools.tavily import tavily_search

    try:
        agent = Agent(
            model=model,
            tools=[tavily_search],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test4' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_agent_with_long_prompt():
    """Test 5: Agent WITH the actual long system prompt from runner."""
    print("\n=== TEST 5: Strands Agent WITH LONG system prompt ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    # The actual prompt from runner.py
    # ruff: noqa: E501
    CLAUDE_CODE_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude.\n\n"
    system_prompt = CLAUDE_CODE_PREFIX + """You are a research assistant helping users find and synthesize information about technical topics.

When given a research task:

1. **Understand the request**: Clarify what specific information, papers, tools, or resources the user needs.

2. **Search systematically**: Use web search to find relevant resources. Try multiple query formulations if initial searches don't yield good results.

3. **Evaluate sources**: Prioritize primary sources (original papers, official documentation) over secondary summaries.

4. **Synthesize findings**: Present what you found in a clear, organized way. Include:
   - Specific resources (papers, tools, links) with proper citations
   - Brief descriptions of why each resource is relevant
   - Any connections or relationships between resources

5. **Acknowledge limitations**: Be clear about what you couldn't find or areas of uncertainty.

Your goal is to help the user build a comprehensive understanding of their research topic with actionable, well-sourced information."""

    # Import tavily
    from strands_tools.tavily import tavily_search

    try:
        agent = Agent(
            model=model,
            tools=[tavily_search],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test5' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_short_addition():
    """Test 6: Short addition to the prefix."""
    print("\n=== TEST 6: Short addition to prefix ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    # Just a tiny addition
    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude. Be helpful."

    from strands_tools.tavily import tavily_search

    try:
        agent = Agent(
            model=model,
            tools=[tavily_search],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test6' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_newline_addition():
    """Test 7: Newline then addition."""
    print("\n=== TEST 7: Newline then addition ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    # Newline then short text
    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude.\nBe helpful."

    from strands_tools.tavily import tavily_search

    try:
        agent = Agent(
            model=model,
            tools=[tavily_search],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test7' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_double_newline_addition():
    """Test 8: Double newline then addition."""
    print("\n=== TEST 8: Double newline then addition ===")
    config = get_config()
    oauth = await get_or_create_oauth()
    model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

    # Double newline (paragraph break) then short text
    system_prompt = "You are Claude Code, Anthropic's official CLI for Claude.\n\nBe helpful."

    from strands_tools.tavily import tavily_search

    try:
        agent = Agent(
            model=model,
            tools=[tavily_search],
            system_prompt=system_prompt,
        )
        response = agent("Say 'test8' and nothing else.")
        print(f"SUCCESS! Response: {response}")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def test_content_blocks_system():
    """Test 9: System prompt as content blocks (directly via model)."""
    print("\n=== TEST 9: Content blocks system prompt (direct) ===")
    config = get_config()
    oauth = await get_or_create_oauth()

    # We need to call the API directly with content blocks for system

    import httpx

    from .model import ANTHROPIC_API, CLAUDE_CODE_USER_AGENT, MESSAGES_ENDPOINT, REQUIRED_BETAS

    access_token = await oauth.ensure_valid_token()

    # Send system as content blocks - first block is Claude Code, second is our instructions
    payload = {
        "model": config.model_id,
        "max_tokens": 100,
        "stream": False,  # Non-streaming for simplicity
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Say 'test9'."}]}
        ],
        "system": [
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"type": "text", "text": "Be helpful and concise."},
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": ",".join(REQUIRED_BETAS),
        "anthropic-dangerous-direct-browser-access": "true",
        "User-Agent": CLAUDE_CODE_USER_AGENT,
        "x-service-name": "claude-code",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{ANTHROPIC_API}{MESSAGES_ENDPOINT}",
                json=payload,
                headers=headers,
            )
            if response.status_code == 200:
                result = response.json()
                text = result.get("content", [{}])[0].get("text", "")
                print(f"SUCCESS! Response: {text}")
                return True
            else:
                print(f"FAILED: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"FAILED: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("  OAuth + Agent Isolation Tests")
    print("=" * 60)

    results = {}

    results["direct_no_tools"] = await test_direct_no_tools()
    results["direct_with_tools"] = await test_direct_with_tools()
    results["agent_no_tools"] = await test_agent_no_tools()
    results["agent_with_tools"] = await test_agent_with_tools()
    results["agent_long_prompt"] = await test_agent_with_long_prompt()
    results["short_addition"] = await test_short_addition()
    results["newline_addition"] = await test_newline_addition()
    results["double_newline_addition"] = await test_double_newline_addition()
    results["content_blocks"] = await test_content_blocks_system()

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {name}: {status}")


if __name__ == "__main__":
    asyncio.run(main())
