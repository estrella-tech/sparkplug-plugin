"""
Base agent runner using Claude Agent SDK.
Each agent gets a system prompt, a set of tools, and runs via query().
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    create_sdk_mcp_server,
    query,
)

CONFIG_DIR = Path.home() / ".sparkplug"
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        key_path = CONFIG_DIR / "anthropic_key.txt"
        if key_path.exists():
            key = key_path.read_text().strip()
    return key


async def run_agent(
    name: str,
    system_prompt: str,
    user_prompt: str,
    tools: list,
    max_turns: int = 15,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Run an agent with the given prompt and tools. Returns the final text output."""
    # Ensure API key is available
    api_key = _get_api_key()
    env = {}
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    # Create in-process MCP server with the agent's tools
    server = create_sdk_mcp_server(name=f"af-{name}", tools=tools)

    # Build allowed tool names
    allowed = [t.name for t in tools]

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={f"af-{name}": server},
        allowed_tools=allowed,
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,
        cwd=str(PROJECT_ROOT),
        env=env,
    )

    all_text = []
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in (message.content or []):
                if hasattr(block, "text") and block.text.strip():
                    all_text.append(block.text)
        elif isinstance(message, ResultMessage):
            # ResultMessage may have text or content
            if hasattr(message, "text") and message.text:
                all_text.append(message.text)
            elif hasattr(message, "content"):
                for block in (message.content or []):
                    if hasattr(block, "text") and block.text.strip():
                        all_text.append(block.text)

    # Return last substantive assistant message (the final report)
    return all_text[-1] if all_text else "(No output from agent)"


def run_agent_sync(
    name: str,
    system_prompt: str,
    user_prompt: str,
    tools: list,
    max_turns: int = 15,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Synchronous wrapper for run_agent."""
    return asyncio.run(run_agent(name, system_prompt, user_prompt, tools, max_turns, model))
