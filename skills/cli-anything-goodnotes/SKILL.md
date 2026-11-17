---
name: "cli-anything-goodnotes"
description: "Author, validate and send Goodnotes content (markdown notes, SVG drawings, Mermaid flowcharts/mindmaps/timelines) through a Goodnotes MCP server"
---

# cli-anything-goodnotes

Use this skill to prepare content for Goodnotes from the command line: markdown
documents, SVG drawings, and Mermaid diagrams (flowchart, mindmap, timeline).
The CLI checks every item against the rules of the Goodnotes MCP tools before
anything is sent, keeps the items in a project file, and can deliver them to a
Goodnotes MCP server.

## What this CLI is and is not

Goodnotes has no command-line tool and no local file API. Its programmatic
surface is an MCP server with three tools: `create_markdown_text_document`,
`draw_svg_image` and `generate_mermaid_diagram`. This CLI does not render
anything and does not read or edit existing Goodnotes notebooks. It builds
validated tool calls and, when a server is configured, sends them.

- Without a server: `note/draw/diagram add`, `item ...`, `validate ...` and
  `export ...` all work.
- Sending (`send`, `backend status`, `backend tools`) needs a server address in
  the environment. There is no built-in address.

## Install

```bash
cd goodnotes/agent-harness
pip install -e .
```

Requires Python 3.10+. Nothing else is installed on the machine.

## Connect to a server (only for `send`)

| Variable | Meaning |
|----------|---------|
| `GOODNOTES_MCP_URL` | Streamable-HTTP endpoint. Must be `https`, or `http` on localhost. |
| `GOODNOTES_MCP_TOKEN` | Optional bearer token for the HTTP endpoint. Never printed. |
| `GOODNOTES_MCP_COMMAND` | Alternative: a command that serves MCP over stdio. |
| `GOODNOTES_MCP_ARGS` | Arguments for that command, shell-style quoting. |
| `GOODNOTES_MCP_TIMEOUT` | Seconds to wait per call. Default 60. |

Check the setup with `cli-anything-goodnotes --json backend status`. It reports
`configured`, `reachable` and any `missing_tools`.

## Usage

```bash
cli-anything-goodnotes                      # interactive REPL (default)
cli-anything-goodnotes --json <command>     # machine-readable output
cli-anything-goodnotes --project p.json ... # load a project; changes auto-save
cli-anything-goodnotes --dry-run ...        # never write the project file
```

### Typical workflow

```bash
cli-anything-goodnotes project new --name "Biology" -o bio.json

cli-anything-goodnotes --project bio.json note add --title "Cell notes" \
  --text "# Cells
- nucleus
- membrane"

cli-anything-goodnotes --project bio.json diagram add --title "Mitosis" \
  --type flowchart --theme-color gray --theme-shade dark \
  --code 'flowchart TD
  A["Prophase"] --> B["Metaphase"] --> C["Anaphase"] --> D["Telophase"]'

cli-anything-goodnotes --project bio.json draw add --title "Cell" \
  --file cell.svg --bg-color white --bg-pattern squared

cli-anything-goodnotes --project bio.json item validate
cli-anything-goodnotes --project bio.json export payload     # tool calls as JSON
cli-anything-goodnotes --project bio.json send               # needs a server
```

## Command groups

| Group | Commands | Purpose |
|-------|----------|---------|
| `project` | `new`, `open`, `save`, `info` | Project file lifecycle |
| `note` | `add` | Markdown document (`--title`, `--text` or `--file`) |
| `draw` | `add` | SVG drawing (`--svg` or `--file`, `--bg-color`, `--bg-pattern`) |
| `diagram` | `add` | Mermaid diagram (`--type flowchart|mindmap|timeline`, `--code` or `--file`, `--theme-color`, `--theme-shade`, background options) |
| `item` | `list`, `show`, `remove`, `validate` | Inspect and check items. `validate` exits 1 if any item is invalid |
| `validate` | `svg`, `mermaid`, `markdown` | Check a loose file without a project |
| `export` | `payload`, `files` | Produce tool calls (`payload`) or `.md/.svg/.mmd` files plus `outbox.json` (`files`) |
| `backend` | `status`, `tools` | Probe the configured MCP server |
| `send` | (command) | Send draft items; `--all` also resends submitted ones |
| `session` | `status`, `undo`, `redo` | In-memory history (REPL and chained use) |

Use `--file -` to read content from stdin.

## Content rules the CLI enforces

- Title: 1 to 120 characters, for every item.
- Markdown: body must not be empty or whitespace-only.
- SVG: root `<svg>` must declare `xmlns="http://www.w3.org/2000/svg"` and
  `xmlns:gn="http://www.goodnotes.com/gn-svg"` (`draw add` adds them if missing;
  `--no-normalize` turns that off). It needs numeric `width` and `height` (>= 1)
  or a non-zero `viewBox`. Not allowed: `linearGradient`, `radialGradient`,
  `pattern`, CDATA, `transform="rotate(...)"`, duplicate attributes, DOCTYPE or
  entities. Colors in `fill`/`stroke`/`stop-color` must be hex (`#RRGGBB`) or
  `none`. Only static shapes, lines and text render.
- Mermaid: type is `flowchart`, `mindmap` or `timeline`, and the first line must
  match (`flowchart`/`graph`, `mindmap`, `timeline`). No backticks, no `#`, no
  `<script>`/`<img>`/`<iframe>`, no `click` directives. Quote flowchart labels
  that contain special characters: `A["Label text"]`. Use `<br/>` for line breaks.
- Background (SVG and Mermaid): color `white|black|yellow`, pattern
  `blank|dotted|squared`. Use `black` for dark mode. Unset options are left out of
  the request so the server applies its defaults (white, dotted).
- Mermaid theme: color `classic|gray|lines`, shade `light|dark`.

## Agent guidance

- Run `--json` and read the result; every failure exits non-zero. A validation
  failure prints `{"error": "validation_failed", "errors": [...]}` listing each
  problem, so fix them all and retry. Nothing is added to the project when
  validation fails.
- Validate before sending: `item validate` (project) or `validate svg|mermaid|markdown`
  (loose file).
- `send` validates every selected item first, then sends one at a time and stops
  at the first failure. Items that were sent are marked `submitted` and are
  skipped by the next plain `send`. Exit code is 1 when anything failed. The
  server's own reply text is in `results[].response`.
- If `backend status` shows `configured: false`, do not guess an address. Use
  `export payload` or `export files` and tell the user a server is needed to send.
- A successful `send` means the server accepted the call. This CLI cannot open
  Goodnotes or confirm what the app shows.
- Send items one at a time or in small batches; the server may rate-limit.
