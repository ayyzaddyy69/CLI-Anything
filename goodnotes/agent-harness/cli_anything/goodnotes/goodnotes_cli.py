"""Stateful CLI harness for Goodnotes content (notes, drawings, diagrams)."""

from __future__ import annotations

import json
import shlex
import sys

import click

from . import __version__
from .core import payload as payload_mod
from .core import project as project_mod
from .core import validate as validate_mod
from .core.session import Session
from .core.validate import ValidationError
from .utils import goodnotes_backend as backend
from .utils.repl_skin import ReplSkin

_session: Session | None = None
_json_output = False


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def emit(data, message: str | None = None) -> None:
    if _json_output:
        click.echo(json.dumps(data, indent=2))
        return
    if message:
        click.echo(message)
    if isinstance(data, dict):
        for key, value in data.items():
            click.echo(f"{key}: {value}")
    elif isinstance(data, list):
        for row in data:
            click.echo("  ".join(f"{k}={v}" for k, v in row.items()) if isinstance(row, dict) else str(row))
    else:
        click.echo(str(data))


def read_text(inline: str | None, file_path: str | None, what: str) -> str:
    if bool(inline) == bool(file_path):
        raise click.UsageError(f"Provide exactly one of --text/--code/--svg or --file for the {what}")
    if file_path:
        if file_path == "-":
            return sys.stdin.read()
        with open(file_path, "r", encoding="utf-8") as fh:
            return fh.read()
    return inline or ""


def fail(exc: Exception) -> None:
    """Turn a domain error into a clear, non-zero exit."""
    if isinstance(exc, ValidationError):
        if _json_output:
            click.echo(json.dumps({"error": "validation_failed", "errors": exc.errors}, indent=2))
            raise SystemExit(1)
        raise click.ClickException("Validation failed:\n  - " + "\n  - ".join(exc.errors))
    if _json_output:
        click.echo(json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2))
        raise SystemExit(1)
    raise click.ClickException(str(exc))


@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON")
@click.option("--project", "project_path", default=None, help="Open a Goodnotes project file")
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Do not save changes to disk")
@click.version_option(__version__, prog_name="cli-anything-goodnotes")
@click.pass_context
def cli(ctx, json_mode: bool, project_path: str | None, dry_run: bool) -> None:
    """Author, validate and send content for Goodnotes: markdown notes, SVG drawings, Mermaid diagrams."""
    global _json_output, _session
    _json_output = json_mode
    _session = Session()
    if project_path:
        try:
            _session.open_project(project_path)
        except (FileNotFoundError, ValueError) as exc:
            fail(exc)

    @ctx.call_on_close
    def _auto_save() -> None:
        if dry_run:
            return
        if project_path and _session and _session.is_open and _session.modified:
            _session.save_project()

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ---------------------------------------------------------------- project


@cli.group()
def project() -> None:
    """Project lifecycle commands."""


@project.command("new")
@click.option("--name", default="Untitled", help="Project name")
@click.option("-o", "--output", "output_path", default=None, help="Save the new project to this file")
def project_new(name: str, output_path: str | None) -> None:
    session = get_session()
    result = project_mod.new_project(session, name=name)
    if output_path:
        result["path"] = project_mod.save_project(session, output_path)["path"]
    emit(result, "Created Goodnotes project")


@project.command("open")
@click.argument("path")
def project_open(path: str) -> None:
    try:
        emit(project_mod.open_project(get_session(), path), "Opened project")
    except (FileNotFoundError, ValueError) as exc:
        fail(exc)


@project.command("save")
@click.argument("path", required=False)
def project_save(path: str | None) -> None:
    try:
        emit(project_mod.save_project(get_session(), path), "Saved project")
    except RuntimeError as exc:
        fail(exc)


@project.command("info")
def project_info() -> None:
    try:
        emit(project_mod.project_info(get_session()), "Project info")
    except RuntimeError as exc:
        fail(exc)


# ------------------------------------------------------------ add content


def background_options(func):
    func = click.option("--bg-pattern", type=click.Choice(validate_mod.BG_PATTERNS), default=None,
                        help="Page pattern (server default: dotted)")(func)
    func = click.option("--bg-color", type=click.Choice(validate_mod.BG_COLORS), default=None,
                        help="Page color (server default: white; black for dark mode)")(func)
    return func


@cli.group()
def note() -> None:
    """Markdown documents (create_markdown_text_document)."""


@note.command("add")
@click.option("--title", required=True, help="Short title (max 120 characters)")
@click.option("--text", default=None, help="Inline markdown")
@click.option("--file", "file_path", default=None, help="Read markdown from a file ('-' for stdin)")
def note_add(title: str, text: str | None, file_path: str | None) -> None:
    try:
        body = read_text(text, file_path, "markdown")
        emit(project_mod.add_markdown(get_session(), title, body), "Added markdown note")
    except (ValidationError, RuntimeError, OSError) as exc:
        fail(exc)


@cli.group()
def draw() -> None:
    """SVG drawings (draw_svg_image)."""


@draw.command("add")
@click.option("--title", required=True, help="Short title (max 120 characters)")
@click.option("--svg", "svg_text", default=None, help="Inline SVG code")
@click.option("--file", "file_path", default=None, help="Read SVG from a file ('-' for stdin)")
@click.option("--no-normalize", is_flag=True, help="Do not add the missing xmlns and xmlns:gn namespaces")
@background_options
def draw_add(title: str, svg_text: str | None, file_path: str | None, no_normalize: bool,
             bg_color: str | None, bg_pattern: str | None) -> None:
    try:
        body = read_text(svg_text, file_path, "SVG")
        result = project_mod.add_svg(get_session(), title, body, color=bg_color, pattern=bg_pattern,
                                     normalize=not no_normalize)
        emit(result, "Added SVG drawing")
    except (ValidationError, RuntimeError, OSError) as exc:
        fail(exc)


@cli.group()
def diagram() -> None:
    """Mermaid diagrams (generate_mermaid_diagram): flowchart, mindmap, timeline."""


@diagram.command("add")
@click.option("--title", required=True, help="Short title (max 120 characters)")
@click.option("--type", "diagram_type", required=True, type=click.Choice(validate_mod.MERMAID_TYPES))
@click.option("--code", default=None, help="Inline Mermaid source")
@click.option("--file", "file_path", default=None, help="Read Mermaid source from a file ('-' for stdin)")
@click.option("--theme-color", type=click.Choice(validate_mod.THEME_COLORS), default=None)
@click.option("--theme-shade", type=click.Choice(validate_mod.THEME_SHADES), default=None)
@background_options
def diagram_add(title, diagram_type, code, file_path, theme_color, theme_shade, bg_color, bg_pattern) -> None:
    try:
        body = read_text(code, file_path, "Mermaid source")
        result = project_mod.add_mermaid(get_session(), title, diagram_type, body, theme_color=theme_color,
                                         theme_shade=theme_shade, color=bg_color, pattern=bg_pattern)
        emit(result, "Added Mermaid diagram")
    except (ValidationError, RuntimeError, OSError) as exc:
        fail(exc)


# -------------------------------------------------------------- inspect


@cli.group()
def item() -> None:
    """Inspect and edit the items in the project."""


@item.command("list")
def item_list() -> None:
    try:
        rows = project_mod.list_items(get_session())
    except RuntimeError as exc:
        fail(exc)
    emit({"items": rows} if _json_output else rows, None if _json_output else f"{len(rows)} item(s)")


@item.command("show")
@click.argument("item_id")
def item_show(item_id: str) -> None:
    try:
        emit(project_mod.get_item(get_session(), item_id))
    except (KeyError, RuntimeError) as exc:
        fail(exc)


@item.command("remove")
@click.argument("item_id")
def item_remove(item_id: str) -> None:
    try:
        emit(project_mod.remove_item(get_session(), item_id), "Removed item")
    except (KeyError, RuntimeError) as exc:
        fail(exc)


@item.command("validate")
@click.argument("item_ids", nargs=-1)
def item_validate(item_ids) -> None:
    """Check items against the Goodnotes tool rules. Exits 1 when any item is invalid."""
    try:
        report = project_mod.validate_items(get_session(), list(item_ids) or None)
    except (KeyError, RuntimeError) as exc:
        fail(exc)
    if _json_output:
        emit(report)
    else:
        for row in report["items"]:
            click.echo(f"{row['id']}: " + ("ok" if not row["errors"] else "; ".join(row["errors"])))
    if not report["valid"]:
        raise SystemExit(1)


@cli.group()
def validate() -> None:
    """Check a file without a project. Exits 1 when it is invalid."""


def _report(errors: list[str]) -> None:
    emit({"valid": not errors, "errors": errors}, None)
    if errors:
        raise SystemExit(1)


@validate.command("svg")
@click.argument("file_path")
@click.option("--normalize", is_flag=True, help="Add missing namespaces before checking")
def validate_svg(file_path: str, normalize: bool) -> None:
    with open(file_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    _report(validate_mod.validate_svg("check", validate_mod.normalize_svg(text) if normalize else text))


@validate.command("mermaid")
@click.argument("file_path")
@click.option("--type", "diagram_type", required=True, type=click.Choice(validate_mod.MERMAID_TYPES))
def validate_mermaid(file_path: str, diagram_type: str) -> None:
    with open(file_path, "r", encoding="utf-8") as fh:
        _report(validate_mod.validate_mermaid("check", diagram_type, fh.read()))


@validate.command("markdown")
@click.argument("file_path")
def validate_markdown(file_path: str) -> None:
    with open(file_path, "r", encoding="utf-8") as fh:
        _report(validate_mod.validate_markdown("check", fh.read()))


# --------------------------------------------------------------- export


@cli.group()
def export() -> None:
    """Produce content without a Goodnotes server."""


@export.command("payload")
@click.argument("item_ids", nargs=-1)
@click.option("-o", "--output", "output_path", default=None, help="Write the payload list to a file")
def export_payload(item_ids, output_path: str | None) -> None:
    """Print MCP tool calls ({tool, arguments}) ready to hand to a Goodnotes MCP client."""
    try:
        items = project_mod.select(get_session(), list(item_ids) or None)
        payloads = [{"id": i["id"], **payload_mod.build_payload(i)} for i in items]
    except (ValidationError, KeyError, RuntimeError) as exc:
        fail(exc)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(payloads, fh, indent=2)
        emit({"path": output_path, "payloads": len(payloads)}, "Wrote payloads")
    else:
        click.echo(json.dumps(payloads, indent=2))


@export.command("files")
@click.argument("out_dir")
@click.argument("item_ids", nargs=-1)
@click.option("--overwrite", is_flag=True, help="Replace existing files")
def export_files(out_dir: str, item_ids, overwrite: bool) -> None:
    """Write .md/.svg/.mmd sources and an outbox.json of payloads into OUT_DIR."""
    try:
        emit(project_mod.export_files(get_session(), out_dir, list(item_ids) or None, overwrite), "Exported files")
    except (ValidationError, KeyError, RuntimeError, ValueError, OSError) as exc:
        fail(exc)


# -------------------------------------------------------------- backend


@cli.group(name="backend")
def backend_group() -> None:
    """The Goodnotes MCP server connection."""


@backend_group.command("status")
def backend_status() -> None:
    """Show the configuration and probe the server. The token is never printed."""
    emit(backend.is_available(), "Goodnotes MCP server")


@backend_group.command("tools")
def backend_tools() -> None:
    """List the tools the configured server offers."""
    try:
        emit({"tools": backend.list_tools()} if _json_output else backend.list_tools(), "Server tools")
    except backend.BackendError as exc:
        fail(exc)


@cli.command()
@click.argument("item_ids", nargs=-1)
@click.option("--all", "send_all", is_flag=True, help="Send every item, including ones already sent")
def send(item_ids, send_all: bool) -> None:
    """Send items to Goodnotes through the MCP server and mark them submitted.

    With no ids, sends the items still in draft. Stops at the first failure.
    """
    session = get_session()
    try:
        items = project_mod.select(session, list(item_ids) or None, include_submitted=send_all)
        if not items:
            raise click.ClickException("Nothing to send. Pass item ids or --all.")
        built = [(i, payload_mod.build_payload(i)) for i in items]  # validate everything first
        config = backend.load_config()
        if not config.transport:
            raise backend.BackendError(backend.SETUP_HINT)
    except (ValidationError, KeyError, RuntimeError, backend.BackendError) as exc:
        fail(exc)
    results = []
    for entry, call in built:
        try:
            outcome = backend.call_tool(call["tool"], call["arguments"], config)
        except backend.BackendError as exc:
            results.append({"id": entry["id"], "ok": False, "error": str(exc)})
            break
        ok = not outcome["is_error"]
        results.append({"id": entry["id"], "ok": ok, "tool": call["tool"], "response": outcome["text"]})
        if not ok:
            break
        project_mod.mark_submitted(session, entry["id"], {"text": outcome["text"]})
    summary = {"sent": sum(1 for r in results if r["ok"]), "requested": len(built), "results": results}
    emit(summary, "Send complete" if summary["sent"] == len(built) else "Send stopped early")
    if summary["sent"] != len(built):
        raise SystemExit(1)


# -------------------------------------------------------------- session


@cli.group()
def session() -> None:
    """Session state commands."""


@session.command("status")
def session_status() -> None:
    emit(get_session().status(), "Session status")


@session.command("undo")
def session_undo() -> None:
    ok = get_session().undo()
    emit({"action": "undo", "success": ok}, "Undo complete" if ok else "Nothing to undo")


@session.command("redo")
def session_redo() -> None:
    ok = get_session().redo()
    emit({"action": "redo", "success": ok}, "Redo complete" if ok else "Nothing to redo")


# ----------------------------------------------------------------- repl

REPL_COMMANDS = {
    "new [name]": "Create a project",
    "open <path>": "Open a project file",
    "save [path]": "Save the project",
    "note <title> :: <markdown>": "Add a markdown note",
    "diagram <flowchart|mindmap|timeline> <title> :: <code>": "Add a Mermaid diagram",
    "list": "List items",
    "check": "Validate every item",
    "send": "Send draft items to the Goodnotes MCP server",
    "backend": "Probe the MCP server",
    "undo / redo": "Step through changes",
    "quit": "Exit",
}


@cli.command()
def repl() -> None:
    """Interactive REPL."""
    session_obj = get_session()
    skin = ReplSkin("goodnotes", version=__version__)
    skin.print_banner()
    prompt_session = skin.create_prompt_session()
    while True:
        name = (session_obj.project_path or "(unsaved)") if session_obj.is_open else ""
        line = skin.get_input(prompt_session, project_name=name, modified=session_obj.modified).strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            if session_obj.is_open and session_obj.modified:
                skin.warning("Unsaved changes. Use 'save <path>' first, or 'quit' again to leave.")
                if skin.get_input(prompt_session, project_name=name, modified=True).strip() not in ("quit", "exit", "q"):
                    continue
            skin.print_goodbye()
            return
        if line == "help":
            skin.help(REPL_COMMANDS)
            continue
        head, _, rest = line.partition(" ")
        try:
            if head == "new":
                project_mod.new_project(session_obj, name=rest or "Untitled")
                skin.success("Created project")
            elif head == "open":
                project_mod.open_project(session_obj, rest)
                skin.success(f"Opened {rest}")
            elif head == "save":
                skin.success(f"Saved {project_mod.save_project(session_obj, rest or None)['path']}")
            elif head == "note":
                title, _, body = rest.partition("::")
                skin.success(f"Added {project_mod.add_markdown(session_obj, title.strip(), body.strip())['id']}")
            elif head == "diagram":
                kind, _, tail = rest.partition(" ")
                title, _, body = tail.partition("::")
                skin.success(f"Added {project_mod.add_mermaid(session_obj, title.strip(), kind, body.strip().replace(chr(92) + 'n', chr(10)))['id']}")
            elif head == "list":
                rows = project_mod.list_items(session_obj)
                skin.table(["id", "kind", "title", "status"], [[r["id"], r["kind"], r["title"], r["status"]] for r in rows])
            elif head == "check":
                report = project_mod.validate_items(session_obj)
                for row in report["items"]:
                    (skin.success if not row["errors"] else skin.error)(f"{row['id']}: " + ("ok" if not row["errors"] else "; ".join(row["errors"])))
            elif head == "backend":
                skin.status("server", backend.is_available()["message"])
            elif head == "undo":
                skin.info("Undone" if session_obj.undo() else "Nothing to undo")
            elif head == "redo":
                skin.info("Redone" if session_obj.redo() else "Nothing to redo")
            elif head == "send":
                _send_in_repl(session_obj, skin)
            else:
                skin.error(f"Unknown command {head!r}. Type 'help'.")
        except (ValidationError, KeyError, RuntimeError, OSError, ValueError, backend.BackendError) as exc:
            skin.error("; ".join(exc.errors) if isinstance(exc, ValidationError) else str(exc))


def _send_in_repl(session_obj: Session, skin: ReplSkin) -> None:
    config = backend.load_config()
    if not config.transport:
        raise backend.BackendError(backend.SETUP_HINT)
    for entry in project_mod.select(session_obj, None, include_submitted=False):
        call = payload_mod.build_payload(entry)
        outcome = backend.call_tool(call["tool"], call["arguments"], config)
        if outcome["is_error"]:
            skin.error(f"{entry['id']}: {outcome['text']}")
            return
        project_mod.mark_submitted(session_obj, entry["id"], {"text": outcome["text"]})
        skin.success(f"Sent {entry['id']}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
