"""End-to-end tests: the installed CLI as a subprocess, plus real MCP round trips.

Goodnotes has no local binary, so the "real backend" here is the MCP protocol.
The tests start ``fake_goodnotes_server.py`` (same tool names and argument
schema as the Goodnotes tools, no rendering) over stdio and over local
streamable HTTP, and check the exact tool calls it receives. They do not prove
that the hosted Goodnotes service accepts the content; see TEST.md.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_SERVER = os.path.join(HERE, "fake_goodnotes_server.py")

SVG = '<svg width="80" height="80"><circle cx="40" cy="40" r="30" fill="#2266CC"/></svg>'
FLOW = 'flowchart TD\n  A["Start"] --> B{"Ready?"}\n  B -->|"Yes"| C["Ship"]'


def _resolve_cli(name):
    """Resolve the installed command; fall back to ``python -m`` for development.

    Set CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = "cli_anything.goodnotes.goodnotes_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


CLI_BASE = _resolve_cli("cli-anything-goodnotes")
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GOODNOTES_")}


def run(args, env=None, check=True):
    result = subprocess.run(CLI_BASE + args, capture_output=True, text=True, env=env or CLEAN_ENV)
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


def stdio_env(log_path):
    env = dict(CLEAN_ENV)
    env["GOODNOTES_MCP_COMMAND"] = sys.executable
    env["GOODNOTES_MCP_ARGS"] = f'"{FAKE_SERVER}" "{log_path}"'
    env["GOODNOTES_MCP_TIMEOUT"] = "45"
    return env


def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture
def project_file(tmp_path):
    path = str(tmp_path / "demo.json")
    run(["project", "new", "--name", "Demo", "-o", path])
    return path


@pytest.fixture
def filled_project(project_file):
    run(["--project", project_file, "note", "add", "--title", "Study notes", "--text", "# Week 1\n- read\n- write"])
    run(["--project", project_file, "diagram", "add", "--title", "Plan", "--type", "flowchart", "--code", FLOW,
         "--theme-color", "gray", "--theme-shade", "dark"])
    run(["--project", project_file, "draw", "add", "--title", "Dot", "--svg", SVG,
         "--bg-color", "black", "--bg-pattern", "squared"])
    return project_file


class TestCLISubprocess:
    def test_help_and_version(self):
        assert "Goodnotes" in run(["--help"]).stdout
        assert run(["--version"]).stdout.strip().endswith("1.0.0")

    def test_json_project_lifecycle(self, project_file):
        info = json.loads(run(["--json", "--project", project_file, "project", "info"]).stdout)
        assert info["name"] == "Demo" and info["items"] == 0

    def test_add_list_remove(self, filled_project):
        listing = json.loads(run(["--json", "--project", filled_project, "item", "list"]).stdout)["items"]
        assert [(i["id"], i["kind"]) for i in listing] == [("item-1", "markdown"), ("item-2", "mermaid"), ("item-3", "svg")]
        run(["--project", filled_project, "item", "remove", "item-2"])
        after = json.loads(run(["--json", "--project", filled_project, "item", "list"]).stdout)["items"]
        assert [i["id"] for i in after] == ["item-1", "item-3"]

    def test_dry_run_does_not_save(self, project_file):
        run(["--dry-run", "--project", project_file, "note", "add", "--title", "T", "--text", "x"])
        info = json.loads(run(["--json", "--project", project_file, "project", "info"]).stdout)
        assert info["items"] == 0

    def test_invalid_content_fails_with_reasons(self, project_file):
        r = run(["--project", project_file, "draw", "add", "--title", "Bad", "--svg",
                 '<svg width="5" height="5"><rect width="2" height="2" fill="red" transform="rotate(5)"/></svg>'],
                check=False)
        assert r.returncode == 1 and "hex color" in r.stderr and "rotate" in r.stderr
        j = run(["--json", "--project", project_file, "diagram", "add", "--title", "Bad", "--type", "mindmap",
                 "--code", "flowchart TD"], check=False)
        body = json.loads(j.stdout)
        assert j.returncode == 1 and body["error"] == "validation_failed" and body["errors"]

    def test_rejects_both_or_neither_source(self, project_file):
        assert run(["--project", project_file, "note", "add", "--title", "T"], check=False).returncode != 0
        assert run(["--project", project_file, "note", "add", "--title", "T", "--text", "a", "--file", "b"],
                   check=False).returncode != 0

    def test_content_from_stdin(self, project_file):
        r = subprocess.run(CLI_BASE + ["--project", project_file, "note", "add", "--title", "Piped", "--file", "-"],
                           input="# piped", capture_output=True, text=True, env=CLEAN_ENV)
        assert r.returncode == 0, r.stderr

    def test_standalone_validate(self, tmp_path):
        good, bad = tmp_path / "good.mmd", tmp_path / "bad.mmd"
        good.write_text(FLOW)
        bad.write_text("flowchart TD\n  A --> B #x")
        assert run(["validate", "mermaid", str(good), "--type", "flowchart"]).returncode == 0
        assert run(["validate", "mermaid", str(bad), "--type", "flowchart"], check=False).returncode == 1
        raw = tmp_path / "raw.svg"
        raw.write_text(SVG)
        assert run(["validate", "svg", str(raw)], check=False).returncode == 1
        assert run(["validate", "svg", str(raw), "--normalize"]).returncode == 0

    def test_export_payload_matches_tool_schemas(self, filled_project, tmp_path):
        out = tmp_path / "payloads.json"
        run(["--project", filled_project, "export", "payload", "-o", str(out)])
        calls = {c["tool"]: c["arguments"] for c in json.load(open(out))}
        assert calls["create_markdown_text_document"] == {"title": "Study notes", "rawMarkdown": "# Week 1\n- read\n- write"}
        assert calls["generate_mermaid_diagram"]["theme"] == {"color": "gray", "shade": "dark"}
        assert calls["generate_mermaid_diagram"]["diagramType"] == "flowchart"
        assert calls["draw_svg_image"]["background"] == {"color": "black", "pattern": "squared"}
        assert 'xmlns:gn="http://www.goodnotes.com/gn-svg"' in calls["draw_svg_image"]["svgCode"]

    def test_export_files(self, filled_project, tmp_path):
        out = str(tmp_path / "out")
        result = json.loads(run(["--json", "--project", filled_project, "export", "files", out]).stdout)
        for f in result["files"]:
            assert os.path.getsize(f["path"]) > 0
            print(f"\n  exported: {f['path']} ({f['bytes']:,} bytes)")
        svg_file = [f["path"] for f in result["files"] if f["path"].endswith(".svg")][0]
        assert open(svg_file).read().startswith("<svg")

    def test_send_without_server_fails_clearly_and_changes_nothing(self, filled_project):
        r = run(["--project", filled_project, "send"], check=False)
        assert r.returncode == 1 and "GOODNOTES_MCP_URL" in r.stderr
        listing = json.loads(run(["--json", "--project", filled_project, "item", "list"]).stdout)["items"]
        assert {i["status"] for i in listing} == {"draft"}

    def test_backend_status_unconfigured(self):
        status = json.loads(run(["--json", "backend", "status"]).stdout)
        assert status["configured"] is False


class TestMcpStdio:
    def test_status_lists_the_three_tools(self, tmp_path):
        env = stdio_env(tmp_path / "log.jsonl")
        status = json.loads(run(["--json", "backend", "status"], env=env).stdout)
        assert status["reachable"] and status["missing_tools"] == []
        assert sorted(status["tools"]) == ["create_markdown_text_document", "draw_svg_image", "generate_mermaid_diagram"]

    def test_send_delivers_exact_arguments_and_marks_submitted(self, filled_project, tmp_path):
        log = str(tmp_path / "log.jsonl")
        env = stdio_env(log)
        result = json.loads(run(["--json", "--project", filled_project, "send"], env=env).stdout)
        assert result["sent"] == 3 and all(r["ok"] for r in result["results"])
        received = {c["tool"]: c["arguments"] for c in read_log(log)}
        assert received["create_markdown_text_document"]["title"] == "Study notes"
        assert received["generate_mermaid_diagram"]["theme"] == {"color": "gray", "shade": "dark"}
        assert received["draw_svg_image"]["background"] == {"color": "black", "pattern": "squared"}
        listing = json.loads(run(["--json", "--project", filled_project, "item", "list"]).stdout)["items"]
        assert {i["status"] for i in listing} == {"submitted"}
        # a second plain send has nothing left; --all resends
        assert run(["--project", filled_project, "send"], env=env, check=False).returncode == 1
        again = json.loads(run(["--json", "--project", filled_project, "send", "--all", "item-1"], env=env).stdout)
        assert again["sent"] == 1 and len(read_log(log)) == 4

    def test_server_error_stops_send_and_keeps_later_items_draft(self, project_file, tmp_path):
        log = str(tmp_path / "log.jsonl")
        env = stdio_env(log)
        for title in ("First", "reject this one", "Third"):
            run(["--project", project_file, "note", "add", "--title", title, "--text", "body"])
        r = run(["--json", "--project", project_file, "send"], env=env, check=False)
        result = json.loads(r.stdout)
        assert r.returncode == 1 and result["sent"] == 1 and result["requested"] == 3
        assert [(x["id"], x["ok"]) for x in result["results"]] == [("item-1", True), ("item-2", False)]
        assert "Error executing tool" in result["results"][1]["response"]  # server error text is surfaced
        statuses = {i["id"]: i["status"] for i in
                    json.loads(run(["--json", "--project", project_file, "item", "list"]).stdout)["items"]}
        assert statuses == {"item-1": "submitted", "item-2": "draft", "item-3": "draft"}
        assert [c["arguments"]["title"] for c in read_log(log)] == ["First", "reject this one"]

    def test_unreachable_server_reports_error(self, filled_project):
        env = dict(CLEAN_ENV)
        env.update({"GOODNOTES_MCP_COMMAND": "definitely-not-a-real-binary", "GOODNOTES_MCP_TIMEOUT": "10"})
        r = run(["--json", "--project", filled_project, "send"], env=env, check=False)
        result = json.loads(r.stdout)
        assert r.returncode == 1 and result["sent"] == 0
        assert "Could not use the Goodnotes MCP server" in result["results"][0]["error"]
        listing = json.loads(run(["--json", "--project", filled_project, "item", "list"]).stdout)["items"]
        assert {i["status"] for i in listing} == {"draft"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(tmp_path):
    port, log = _free_port(), str(tmp_path / "http-log.jsonl")
    proc = subprocess.Popen([sys.executable, FAKE_SERVER, log, "--http", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
        except urllib.error.HTTPError:
            break  # the server answered (404/405 is fine)
        except OSError:
            time.sleep(0.3)
        else:
            break
    else:
        proc.kill()
        raise RuntimeError("stand-in HTTP server did not start")
    yield f"http://127.0.0.1:{port}/mcp", log
    proc.terminate()
    proc.wait(timeout=10)


class TestMcpHttp:
    def test_send_over_streamable_http(self, filled_project, http_server):
        url, log = http_server
        env = dict(CLEAN_ENV)
        env.update({"GOODNOTES_MCP_URL": url, "GOODNOTES_MCP_TOKEN": "test-token", "GOODNOTES_MCP_TIMEOUT": "30"})
        status = json.loads(run(["--json", "backend", "status"], env=env).stdout)
        assert status["reachable"] and status["transport"] == "http" and status["token_set"] is True
        assert "test-token" not in json.dumps(status)
        result = json.loads(run(["--json", "--project", filled_project, "send"], env=env).stdout)
        assert result["sent"] == 3
        assert {c["tool"] for c in read_log(log)} == {
            "create_markdown_text_document", "generate_mermaid_diagram", "draw_svg_image"}
