# cli-anything-goodnotes

A command-line harness for creating [Goodnotes](https://www.goodnotes.com) content: markdown notes, SVG
drawings and Mermaid diagrams (flowchart, mindmap, timeline).

## What it does, and what it does not

Goodnotes has no command-line tool and no local file API, so this harness does
not drive the app. It works with the **Goodnotes MCP server**, which offers three
tools:

| Tool | Harness command |
|------|-----------------|
| `create_markdown_text_document` | `note add` |
| `draw_svg_image` | `draw add` |
| `generate_mermaid_diagram` | `diagram add` |

The harness:

1. keeps your items in a project file,
2. checks each item against the tool rules before anything is sent
   (title length, SVG namespaces and forbidden elements, hex colors, Mermaid types
   and forbidden characters, background and theme values),
3. exports ready-to-use tool calls (`export payload`) or source files (`export files`),
4. sends items to a Goodnotes MCP server you configure (`send`).

It does **not** render content, read your notebooks, or edit existing documents.
The server address is not built in. You supply it. See "Connect a server".

## Install

```bash
cd goodnotes/agent-harness
pip install -e .
cli-anything-goodnotes --help
```

Python 3.10+. Dependencies (`click`, `prompt-toolkit`, `mcp`, `httpx`, `defusedxml`) install with the package.

## Quick start

```bash
cli-anything-goodnotes project new --name "Study" -o study.json
cli-anything-goodnotes --project study.json note add --title "Week 1" --text "# Week 1
- read ch. 1"
cli-anything-goodnotes --project study.json diagram add --title "Plan" --type mindmap \
  --code 'mindmap
  root("Plan")
    a("Read")
    b("Write")'
cli-anything-goodnotes --project study.json item validate
cli-anything-goodnotes --project study.json export payload
```

Running `cli-anything-goodnotes` with no subcommand opens the REPL.

## Connect a server (needed only for `send`)

```bash
export GOODNOTES_MCP_URL="https://<your-goodnotes-mcp-endpoint>/mcp"
export GOODNOTES_MCP_TOKEN="<token, if the server needs one>"
cli-anything-goodnotes backend status      # configured / reachable / tools
cli-anything-goodnotes --project study.json send
```

For a server you start as a local process, set `GOODNOTES_MCP_COMMAND` and `GOODNOTES_MCP_ARGS` instead.
`http://` is accepted only for localhost. The token is never printed.

## Run the tests

```bash
pip install -e ".[dev]"
CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/goodnotes/tests -v -s
```

The end-to-end tests start a stand-in MCP server (`tests/fake_goodnotes_server.py`) over stdio and over
local HTTP. See `tests/TEST.md` for what that does and does not prove.
