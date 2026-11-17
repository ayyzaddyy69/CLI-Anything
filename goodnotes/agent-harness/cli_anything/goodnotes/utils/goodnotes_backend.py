"""MCP client for a Goodnotes MCP server.

Goodnotes ships no command-line tool or local file API. Its programmatic
surface is an MCP server exposing three tools: ``create_markdown_text_document``,
``draw_svg_image`` and ``generate_mermaid_diagram``. This module talks to such a
server. The CLI does not know a server address by default: you must point it at
one with environment variables.

    GOODNOTES_MCP_URL       Streamable-HTTP endpoint (https, or http on loopback)
    GOODNOTES_MCP_TOKEN     Optional bearer token sent with HTTP requests
    GOODNOTES_MCP_COMMAND   Alternative: a command that serves MCP over stdio
    GOODNOTES_MCP_ARGS      Arguments for that command (shell-style quoting)
    GOODNOTES_MCP_TIMEOUT   Seconds to wait for one call (default 60)

Authoring, validation and export work without a server.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

REQUIRED_TOOLS = ("create_markdown_text_document", "draw_svg_image", "generate_mermaid_diagram")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
SETUP_HINT = (
    "No Goodnotes MCP server is configured. Set GOODNOTES_MCP_URL (and GOODNOTES_MCP_TOKEN "
    "if it needs one) or GOODNOTES_MCP_COMMAND. Use 'export payload' or 'export files' to "
    "produce the content without a server."
)


class BackendError(RuntimeError):
    """The Goodnotes MCP server is missing, unreachable or returned an error."""


@dataclass
class BackendConfig:
    url: str | None = None
    token: str | None = None
    command: str | None = None
    args: list[str] | None = None
    timeout: float = 60.0

    @property
    def transport(self) -> str | None:
        if self.url:
            return "http"
        if self.command:
            return "stdio"
        return None

    def describe(self) -> dict:
        """Describe the setup without exposing the token."""
        return {
            "transport": self.transport,
            "url": self.url,
            "command": self.command,
            "args": self.args,
            "token_set": bool(self.token),
            "timeout": self.timeout,
        }


def load_config(env: dict[str, str] | None = None) -> BackendConfig:
    env = os.environ if env is None else env
    url = (env.get("GOODNOTES_MCP_URL") or "").strip() or None
    command = (env.get("GOODNOTES_MCP_COMMAND") or "").strip() or None
    try:
        timeout = float(env.get("GOODNOTES_MCP_TIMEOUT") or 60)
    except ValueError as exc:
        raise BackendError("GOODNOTES_MCP_TIMEOUT must be a number of seconds") from exc
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise BackendError("GOODNOTES_MCP_URL must be an http(s) URL")
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK:
            raise BackendError("GOODNOTES_MCP_URL must use https unless it points at localhost")
    return BackendConfig(
        url=url,
        token=(env.get("GOODNOTES_MCP_TOKEN") or "").strip() or None,
        command=command,
        args=shlex.split(env.get("GOODNOTES_MCP_ARGS") or ""),
        timeout=timeout,
    )


@asynccontextmanager
async def _open_session(config: BackendConfig):
    from mcp import ClientSession

    if config.transport == "http":
        import httpx

        try:
            from mcp.client.streamable_http import streamable_http_client as http_client
        except ImportError:  # older MCP SDK releases use the previous name
            from mcp.client.streamable_http import streamablehttp_client as http_client
        headers = {"Authorization": f"Bearer {config.token}"} if config.token else None
        client = httpx.AsyncClient(headers=headers, timeout=config.timeout)
        async with client:
            async with http_client(config.url, http_client=client) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    elif config.transport == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=config.command, args=config.args or [])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        raise BackendError(SETUP_HINT)


async def _with_session(config: BackendConfig, action):
    async def run():
        async with _open_session(config) as session:
            return await action(session)

    try:
        return await asyncio.wait_for(run(), timeout=config.timeout)
    except asyncio.TimeoutError as exc:
        raise BackendError(f"The Goodnotes MCP server did not answer within {config.timeout:g} seconds") from exc
    except BackendError:
        raise
    except Exception as exc:  # transport and protocol errors vary by SDK version
        raise BackendError(f"Could not use the Goodnotes MCP server: {type(exc).__name__}: {exc}") from exc


def list_tools(config: BackendConfig | None = None) -> list[str]:
    config = config or load_config()

    async def action(session):
        result = await session.list_tools()
        return [tool.name for tool in result.tools]

    return asyncio.run(_with_session(config, action))


def is_available(config: BackendConfig | None = None) -> dict:
    """Probe the server. Never raises; reports what is missing."""
    try:
        config = config or load_config()
    except BackendError as exc:
        return {"configured": False, "reachable": False, "message": str(exc)}
    if not config.transport:
        return {"configured": False, "reachable": False, "message": SETUP_HINT, **config.describe()}
    try:
        tools = list_tools(config)
    except BackendError as exc:
        return {"configured": True, "reachable": False, "message": str(exc), **config.describe()}
    missing = [t for t in REQUIRED_TOOLS if t not in tools]
    return {
        "configured": True,
        "reachable": True,
        "tools": tools,
        "missing_tools": missing,
        "message": "ready" if not missing else f"server is missing tools: {', '.join(missing)}",
        **config.describe(),
    }


def call_tool(tool: str, arguments: dict[str, Any], config: BackendConfig | None = None) -> dict:
    """Call one Goodnotes tool and return ``{"is_error", "text", "structured"}``."""
    config = config or load_config()

    async def action(session):
        result = await session.call_tool(tool, arguments)
        texts = [block.text for block in (result.content or []) if getattr(block, "type", None) == "text"]
        return {
            "is_error": bool(getattr(result, "is_error", getattr(result, "isError", False))),
            "text": "\n".join(texts),
            "structured": getattr(result, "structured_content", getattr(result, "structuredContent", None)),
        }

    return asyncio.run(_with_session(config, action))
