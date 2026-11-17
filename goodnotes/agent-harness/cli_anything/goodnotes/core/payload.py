"""Build Goodnotes MCP tool-call payloads from project items."""

from __future__ import annotations

from .validate import ValidationError, validate_markdown, validate_mermaid, validate_svg

TOOL_FOR_KIND = {
    "markdown": "create_markdown_text_document",
    "svg": "draw_svg_image",
    "mermaid": "generate_mermaid_diagram",
}
EXTENSION_FOR_KIND = {"markdown": "md", "svg": "svg", "mermaid": "mmd"}


def validate_item(item: dict) -> list[str]:
    kind = item.get("kind")
    if kind == "markdown":
        return validate_markdown(item.get("title"), item.get("markdown"))
    if kind == "svg":
        return validate_svg(item.get("title"), item.get("svg"))
    if kind == "mermaid":
        return validate_mermaid(item.get("title"), item.get("diagram_type"), item.get("code"))
    return [f"unknown item kind {kind!r}"]


def _background(item: dict) -> dict | None:
    background = {k: v for k, v in (item.get("background") or {}).items() if v}
    return background or None


def build_payload(item: dict) -> dict:
    """Return ``{"tool": ..., "arguments": ...}`` matching the MCP input schema.

    Optional fields are omitted unless set, so the server applies its own
    defaults (white background, dotted pattern, classic light theme).
    """
    errors = validate_item(item)
    if errors:
        raise ValidationError(errors)
    kind = item["kind"]
    if kind == "markdown":
        arguments = {"title": item["title"], "rawMarkdown": item["markdown"]}
    elif kind == "svg":
        arguments = {"title": item["title"], "svgCode": item["svg"]}
        if _background(item):
            arguments["background"] = _background(item)
    else:
        arguments = {
            "title": item["title"],
            "diagramType": item["diagram_type"],
            "mermaidCode": item["code"],
        }
        theme = {k: v for k, v in (item.get("theme") or {}).items() if v}
        if theme:
            arguments["theme"] = theme
        if _background(item):
            arguments["background"] = _background(item)
    return {"tool": TOOL_FOR_KIND[kind], "arguments": arguments}


def item_body(item: dict) -> str:
    return {"markdown": item.get("markdown"), "svg": item.get("svg"), "mermaid": item.get("code")}[item["kind"]]
