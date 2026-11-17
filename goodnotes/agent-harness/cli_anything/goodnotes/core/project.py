"""Project operations: a project is an ordered list of Goodnotes content items."""

from __future__ import annotations

import copy
import os
import re
from datetime import datetime, timezone

from . import payload as payload_mod
from .session import Session
from .validate import (
    ValidationError,
    check_background,
    check_theme,
    normalize_svg,
)

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_project(session: Session, name: str = "Untitled") -> dict:
    state = {"version": SCHEMA_VERSION, "name": name, "created": _now(), "next_id": 1, "items": []}
    session.reset(state, None, modified=True)
    return copy.deepcopy(state)


def open_project(session: Session, path: str) -> dict:
    return session.open_project(path)


def save_project(session: Session, path: str | None = None) -> dict:
    target = session.save_project(path)
    return {"path": target, "items": len(session.state["items"])}


def project_info(session: Session) -> dict:
    state = session.require_open()
    by_kind: dict[str, int] = {}
    for item in state["items"]:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    return {
        "name": state["name"],
        "path": session.project_path,
        "items": len(state["items"]),
        "by_kind": by_kind,
        "submitted": sum(1 for i in state["items"] if i.get("status") == "submitted"),
    }


def _add(session: Session, item: dict) -> dict:
    state = session.require_open()
    errors = payload_mod.validate_item(item)
    errors += check_background((item.get("background") or {}).get("color"), (item.get("background") or {}).get("pattern"))
    errors += check_theme((item.get("theme") or {}).get("color"), (item.get("theme") or {}).get("shade"))
    if errors:
        raise ValidationError(errors)
    session.checkpoint()
    item["id"] = f"item-{state['next_id']}"
    item["status"] = "draft"
    item["created"] = _now()
    state["next_id"] += 1
    state["items"].append(item)
    session.modified = True
    return summarize(item)


def add_markdown(session: Session, title: str, markdown: str) -> dict:
    return _add(session, {"kind": "markdown", "title": title, "markdown": markdown})


def add_svg(session: Session, title: str, svg: str, color: str | None = None,
            pattern: str | None = None, normalize: bool = True) -> dict:
    if normalize:
        svg = normalize_svg(svg)
    return _add(session, {"kind": "svg", "title": title, "svg": svg,
                          "background": {"color": color, "pattern": pattern}})


def add_mermaid(session: Session, title: str, diagram_type: str, code: str,
                theme_color: str | None = None, theme_shade: str | None = None,
                color: str | None = None, pattern: str | None = None) -> dict:
    return _add(session, {"kind": "mermaid", "title": title, "diagram_type": diagram_type, "code": code,
                          "theme": {"color": theme_color, "shade": theme_shade},
                          "background": {"color": color, "pattern": pattern}})


def get_item(session: Session, item_id: str) -> dict:
    for item in session.require_open()["items"]:
        if item["id"] == item_id:
            return item
    raise KeyError(f"No item with id {item_id!r}. Run 'item list' to see ids.")


def summarize(item: dict) -> dict:
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "tool": payload_mod.TOOL_FOR_KIND[item["kind"]],
        "status": item.get("status", "draft"),
        "chars": len(payload_mod.item_body(item)),
    }


def list_items(session: Session) -> list[dict]:
    return [summarize(i) for i in session.require_open()["items"]]


def remove_item(session: Session, item_id: str) -> dict:
    state = session.require_open()
    get_item(session, item_id)
    session.checkpoint()
    state["items"] = [i for i in state["items"] if i["id"] != item_id]
    session.modified = True
    return {"removed": item_id, "items": len(state["items"])}


def validate_items(session: Session, ids: list[str] | None = None) -> dict:
    items = [get_item(session, i) for i in ids] if ids else session.require_open()["items"]
    report = [{"id": i["id"], "errors": payload_mod.validate_item(i)} for i in items]
    return {"valid": all(not r["errors"] for r in report), "items": report}


def mark_submitted(session: Session, item_id: str, result: dict) -> None:
    item = get_item(session, item_id)
    session.checkpoint()
    item["status"] = "submitted"
    item["submitted"] = _now()
    item["result"] = result
    session.modified = True


def select(session: Session, ids: list[str] | None, include_submitted: bool = True) -> list[dict]:
    if ids:
        return [get_item(session, i) for i in ids]
    items = session.require_open()["items"]
    return items if include_submitted else [i for i in items if i.get("status") != "submitted"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def export_files(session: Session, out_dir: str, ids: list[str] | None = None, overwrite: bool = False) -> dict:
    """Write each item's source file plus an ``outbox.json`` of ready MCP payloads."""
    import json

    items = select(session, ids)
    if not items:
        raise ValueError("Nothing to export: the project has no items")
    os.makedirs(out_dir, exist_ok=True)
    written, payloads = [], []
    for item in items:
        built = payload_mod.build_payload(item)
        name = f"{item['id']}-{slug(item['title'])}.{payload_mod.EXTENSION_FOR_KIND[item['kind']]}"
        path = os.path.join(out_dir, name)
        if os.path.exists(path) and not overwrite:
            raise FileExistsError(f"{path} exists; pass --overwrite to replace it")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload_mod.item_body(item))
        written.append({"id": item["id"], "path": path, "bytes": os.path.getsize(path)})
        payloads.append({"id": item["id"], **built})
    outbox = os.path.join(out_dir, "outbox.json")
    if os.path.exists(outbox) and not overwrite:
        raise FileExistsError(f"{outbox} exists; pass --overwrite to replace it")
    with open(outbox, "w", encoding="utf-8") as fh:
        json.dump(payloads, fh, indent=2)
    return {"directory": os.path.abspath(out_dir), "files": written, "outbox": outbox}
