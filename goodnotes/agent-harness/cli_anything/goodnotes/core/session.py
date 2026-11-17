"""Session state for Goodnotes projects: in-memory state, undo/redo, locked saves."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field


def _locked_save_json(path: str, data: dict, **dump_kwargs) -> None:
    """Write JSON with an exclusive lock; truncate only after the lock is held."""
    try:
        handle = open(path, "r+", encoding="utf-8")
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        handle = open(path, "w", encoding="utf-8")
    with handle as f:
        locked = False
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, **dump_kwargs)
            f.flush()
        finally:
            if locked:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@dataclass
class Session:
    state: dict | None = None
    project_path: str | None = None
    modified: bool = False
    undo_stack: list[dict] = field(default_factory=list)
    redo_stack: list[dict] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.state is not None

    def require_open(self) -> dict:
        if self.state is None:
            raise RuntimeError("No project is open. Run 'project new' or pass --project <file>.")
        return self.state

    def checkpoint(self) -> None:
        if self.state is not None:
            self.undo_stack.append(copy.deepcopy(self.state))
            self.redo_stack.clear()

    def reset(self, state: dict, path: str | None, modified: bool) -> None:
        self.state = state
        self.project_path = os.path.abspath(path) if path else None
        self.modified = modified
        self.undo_stack.clear()
        self.redo_stack.clear()

    def open_project(self, path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Project not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            try:
                state = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(state, dict) or not isinstance(state.get("items"), list):
            raise ValueError(f"{path} is not a Goodnotes project file")
        self.reset(state, path, modified=False)
        return copy.deepcopy(state)

    def save_project(self, path: str | None = None) -> str:
        state = self.require_open()
        target = os.path.abspath(path or self.project_path or "goodnotes.project.json")
        _locked_save_json(target, state, indent=2)
        self.project_path = target
        self.modified = False
        return target

    def undo(self) -> bool:
        if not self.undo_stack or self.state is None:
            return False
        self.redo_stack.append(copy.deepcopy(self.state))
        self.state = self.undo_stack.pop()
        self.modified = True
        return True

    def redo(self) -> bool:
        if not self.redo_stack or self.state is None:
            return False
        self.undo_stack.append(copy.deepcopy(self.state))
        self.state = self.redo_stack.pop()
        self.modified = True
        return True

    def status(self) -> dict:
        return {
            "project_open": self.is_open,
            "project_path": self.project_path,
            "modified": self.modified,
            "items": len(self.state["items"]) if self.state else 0,
            "undo_depth": len(self.undo_stack),
            "redo_depth": len(self.redo_stack),
        }
