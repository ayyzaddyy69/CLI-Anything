"""A stand-in Goodnotes MCP server for tests.

It exposes the three Goodnotes tool names with the same argument names and
enum values as the real tool schemas, validates them, and appends every call
to the JSONL file given as the first argument. With "--http PORT" it serves
streamable HTTP on localhost instead of stdio. It does not render anything.
It exists to exercise this harness's MCP client over a real stdio transport.
"""

import json
import sys
from typing import Literal, Optional

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

server = MCPServer("fake-goodnotes")
_LOG_PATH = None


class Background(BaseModel):
    color: Optional[Literal["white", "black", "yellow"]] = None
    pattern: Optional[Literal["blank", "dotted", "squared"]] = None


class Theme(BaseModel):
    color: Optional[Literal["classic", "gray", "lines"]] = None
    shade: Optional[Literal["light", "dark"]] = None


def _log(tool: str, arguments: dict) -> None:
    path = _LOG_PATH
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": tool, "arguments": arguments}) + "\n")


@server.tool()
def create_markdown_text_document(rawMarkdown: str, title: str) -> str:
    _log("create_markdown_text_document", {"rawMarkdown": rawMarkdown, "title": title})
    if not rawMarkdown.strip():
        raise ValueError("rawMarkdown must not be blank")
    if title.startswith("reject"):
        raise ValueError("title rejected by the stand-in server")
    return f"Created markdown document '{title}'"


@server.tool()
def draw_svg_image(title: str, svgCode: str, background: Optional[Background] = None) -> str:
    _log("draw_svg_image", {"title": title, "svgCode": svgCode,
                            "background": background.model_dump(exclude_none=True) if background else None})
    if "xmlns:gn" not in svgCode:
        raise ValueError("svgCode must declare the gn namespace")
    return f"Drew SVG '{title}'"


@server.tool()
def generate_mermaid_diagram(title: str, diagramType: Literal["flowchart", "mindmap", "timeline"],
                             mermaidCode: str, background: Optional[Background] = None,
                             theme: Optional[Theme] = None) -> str:
    _log("generate_mermaid_diagram", {
        "title": title, "diagramType": diagramType, "mermaidCode": mermaidCode,
        "background": background.model_dump(exclude_none=True) if background else None,
        "theme": theme.model_dump(exclude_none=True) if theme else None})
    return f"Generated {diagramType} '{title}'"


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        _LOG_PATH = args.pop(0)
    if args[:1] == ["--http"]:
        server.run("streamable-http", host="127.0.0.1", port=int(args[1]))
    else:
        server.run("stdio")
