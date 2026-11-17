"""Validation for the three content kinds the Goodnotes MCP server accepts.

The rules mirror the input schema and the tool descriptions of the Goodnotes
MCP tools (``create_markdown_text_document``, ``draw_svg_image`` and
``generate_mermaid_diagram``). Checking locally gives an agent a clear error
before a request goes to the server.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

TITLE_MAX = 120
BG_COLORS = ("white", "black", "yellow")
BG_PATTERNS = ("blank", "dotted", "squared")
MERMAID_TYPES = ("flowchart", "mindmap", "timeline")
THEME_COLORS = ("classic", "gray", "lines")
THEME_SHADES = ("light", "dark")

SVG_NS = "http://www.w3.org/2000/svg"
GN_NS = "http://www.goodnotes.com/gn-svg"

_FORBIDDEN_SVG_TAGS = {"lineargradient", "radialgradient", "pattern"}
_COLOR_ATTRS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color")
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_NUMBER = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(?:px)?\s*$")


class ValidationError(ValueError):
    """Raised when content cannot be accepted by the Goodnotes tools."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def check_title(title: str | None) -> list[str]:
    if title is None or not str(title).strip():
        return ["title must not be empty"]
    if len(title) > TITLE_MAX:
        return [f"title is {len(title)} characters; the limit is {TITLE_MAX}"]
    return []


def check_background(color: str | None, pattern: str | None) -> list[str]:
    errors = []
    if color is not None and color not in BG_COLORS:
        errors.append(f"background color {color!r} is invalid; use one of {', '.join(BG_COLORS)}")
    if pattern is not None and pattern not in BG_PATTERNS:
        errors.append(f"background pattern {pattern!r} is invalid; use one of {', '.join(BG_PATTERNS)}")
    return errors


def check_theme(color: str | None, shade: str | None) -> list[str]:
    errors = []
    if color is not None and color not in THEME_COLORS:
        errors.append(f"theme color {color!r} is invalid; use one of {', '.join(THEME_COLORS)}")
    if shade is not None and shade not in THEME_SHADES:
        errors.append(f"theme shade {shade!r} is invalid; use one of {', '.join(THEME_SHADES)}")
    return errors


# ---------------------------------------------------------------- markdown


def validate_markdown(title: str, markdown: str) -> list[str]:
    errors = check_title(title)
    if markdown is None or not markdown.strip():
        errors.append("markdown must not be empty or whitespace-only")
    return errors


# --------------------------------------------------------------------- svg


def normalize_svg(svg: str) -> str:
    """Add the two namespaces Goodnotes requires when the root tag lacks them."""
    match = re.search(r"<svg\b[^>]*>", svg)
    if not match:
        return svg
    tag = match.group(0)
    additions = ""
    if "xmlns=" not in tag:
        additions += f' xmlns="{SVG_NS}"'
    if "xmlns:gn=" not in tag:
        additions += f' xmlns:gn="{GN_NS}"'
    if not additions:
        return svg
    closing = "/>" if tag.endswith("/>") else ">"
    new_tag = tag[: -len(closing)].rstrip() + additions + closing
    return svg[: match.start()] + new_tag + svg[match.end():]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _positive_number(value: str | None) -> bool:
    if value is None:
        return False
    match = _NUMBER.match(value)
    return bool(match) and float(match.group(1)) >= 1


def validate_svg(title: str, svg: str) -> list[str]:
    """Return a list of problems; an empty list means the SVG is acceptable."""
    errors = check_title(title)
    if svg is None or not svg.strip():
        return errors + ["svg must not be empty"]

    if "<![CDATA[" in svg:
        errors.append("CDATA sections are not supported")
    root_tag = re.search(r"<svg\b[^>]*>", svg)
    if not root_tag:
        return errors + ["svg has no <svg> root element"]
    if 'xmlns="http://www.w3.org/2000/svg"' not in root_tag.group(0).replace("'", '"'):
        errors.append(f'root <svg> must declare xmlns="{SVG_NS}"')
    if 'xmlns:gn="http://www.goodnotes.com/gn-svg"' not in root_tag.group(0).replace("'", '"'):
        errors.append(f'root <svg> must declare xmlns:gn="{GN_NS}"')

    try:
        root = SafeET.fromstring(svg)
    except DefusedXmlException as exc:
        return errors + [f"svg uses a forbidden XML construct: {exc}"]
    except ET.ParseError as exc:
        return errors + [f"svg is not well-formed XML ({exc}); check closed tags, escaped text and duplicate attributes"]

    if _local(root.tag) != "svg":
        errors.append("root element must be <svg>")

    width, height = root.get("width"), root.get("height")
    view_box = root.get("viewBox")
    has_size = _positive_number(width) and _positive_number(height)
    has_view_box = False
    if view_box:
        parts = view_box.replace(",", " ").split()
        try:
            has_view_box = len(parts) == 4 and float(parts[2]) > 0 and float(parts[3]) > 0
        except ValueError:
            has_view_box = False
    if not (has_size or has_view_box):
        errors.append("svg needs numeric width and height (>= 1) or a non-zero viewBox")

    for element in root.iter():
        name = _local(element.tag)
        if name in _FORBIDDEN_SVG_TAGS:
            errors.append(f"<{name}> is not supported; use solid colors")
        transform = element.get("transform", "")
        if re.search(r"\brotate\s*\(", transform, re.IGNORECASE):
            errors.append("transform rotate(...) is not supported; compute the rotated coordinates instead")
        style = element.get("style", "")
        for attr in _COLOR_ATTRS:
            candidates = []
            if element.get(attr) is not None:
                candidates.append(element.get(attr))
            for decl in style.split(";"):
                key, _, val = decl.partition(":")
                if key.strip() == attr and val.strip():
                    candidates.append(val.strip())
            for value in candidates:
                if value.strip().lower() in ("none", "transparent"):
                    continue
                if value.strip().lower().startswith("url("):
                    errors.append(f"{attr}={value!r} references a paint server; use a hex color")
                elif not _HEX.match(value.strip()):
                    errors.append(f"{attr}={value!r} on <{name}> must be a hex color such as #1A2B3C")
    return _dedupe(errors)


# ----------------------------------------------------------------- mermaid

_FORBIDDEN_MERMAID = (
    (re.compile(r"`"), "backticks are not allowed"),
    (re.compile(r"#"), "hash signs are not allowed; use the entity &num; or reword"),
    (re.compile(r"<\s*(script|img|iframe|object|embed)\b", re.IGNORECASE), "HTML elements that load assets or scripts are not allowed"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: URLs are not allowed"),
    (re.compile(r"^\s*click\s", re.IGNORECASE | re.MULTILINE), "click directives are not allowed"),
)
_FIRST_KEYWORDS = {
    "flowchart": ("flowchart", "graph"),
    "mindmap": ("mindmap",),
    "timeline": ("timeline",),
}
_NODE_LABEL = re.compile(r"\b[A-Za-z0-9_]+\s*(?:\[\[|\(\(|\[|\(|\{)([^\]\)\}\n]*)(?:\]\]|\)\)|\]|\)|\})")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9 ,.\-_:;!?'/&<>]*$")


def _has_unquoted_special_label(code: str) -> bool:
    for match in _NODE_LABEL.finditer(code):
        label = match.group(1).strip()
        if label and not label.startswith('"') and not _SAFE_LABEL.match(label):
            return True
    return False


def validate_mermaid(title: str, diagram_type: str, code: str) -> list[str]:
    errors = check_title(title)
    if diagram_type not in MERMAID_TYPES:
        errors.append(f"diagram type {diagram_type!r} is invalid; use one of {', '.join(MERMAID_TYPES)}")
        return errors
    if code is None or not code.strip():
        return errors + ["mermaid code must not be empty"]

    first = next((ln.strip() for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("%%")), "")
    keyword = first.split()[0].lower() if first else ""
    if keyword not in _FIRST_KEYWORDS[diagram_type]:
        errors.append(
            f"first line must start with {' or '.join(_FIRST_KEYWORDS[diagram_type])!r} for a {diagram_type}; found {first[:40]!r}"
        )
    for pattern, message in _FORBIDDEN_MERMAID:
        if pattern.search(code):
            errors.append(message)
    if diagram_type == "flowchart" and _has_unquoted_special_label(code):
        errors.append('flowchart labels with special characters must be quoted, for example A["Label text"]')
    return _dedupe(errors)


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
