# GOODNOTES.md: harness analysis

## Backend analysis (Phase 1)

- **No native engine.** Goodnotes is a closed-source iPadOS/macOS/iOS/Windows/Android/web app. There is no
  CLI, no scripting interface, and no documented file format to manipulate. Notebook files are not a stable
  public surface, so the harness does not touch them.
- **The programmatic surface is an MCP server** with three tools. Their input schemas are the contract:

| Tool | Arguments |
|------|-----------|
| `create_markdown_text_document` | `title` (1-120), `rawMarkdown` (non-blank) |
| `draw_svg_image` | `title`, `svgCode`, optional `background{color: white/black/yellow, pattern: blank/dotted/squared}` |
| `generate_mermaid_diagram` | `title`, `diagramType` (flowchart/mindmap/timeline), `mermaidCode`, optional `theme{color: classic/gray/lines, shade: light/dark}`, optional `background` |

- Tool descriptions add rules the schema does not express (SVG namespaces, no gradients/patterns/CDATA/rotate,
  hex colors, quoted Mermaid labels, no backticks or hash signs). `core/validate.py` encodes them.

## Design decisions

- **Deviation from the "real software is a hard dependency" rule.** There is no software to invoke. The
  harness is an MCP client plus an authoring and validation layer. Rendering stays with the server. The harness
  never rasterizes or previews content in Python.
- **Server address is configuration, not code.** `GOODNOTES_MCP_URL` / `GOODNOTES_MCP_COMMAND`. No default,
  because a guessed address would be wrong and could leak content to a third party. `http` is allowed only on
  loopback. The bearer token is read from the environment and never echoed.
- **Offline first.** Everything except `send` and `backend` works without a server, so agents can author,
  validate and export (`outbox.json`) and hand the calls to any MCP-capable client.
- **Omit unset options.** Background and theme go into a request only when set, so server defaults apply.
- **Validate everything before sending; stop on first failure.** Sent items are marked `submitted` so a retry
  does not duplicate them. Failed and later items stay `draft`.
- **State:** a JSON project file (`items[]`, each `markdown|svg|mermaid`, `draft|submitted`), saved with an
  exclusive lock (`core/session.py`). Undo/redo is in memory per session.

## Not covered

- Reading, listing, searching or editing existing Goodnotes documents (the MCP server exposes no such tool).
- Previews. Rendering is done by Goodnotes, so there is no honest local preview to publish.
