"""Unit tests: validators, payload builder, project state, session, backend config."""

import json
import os

import pytest

from cli_anything.goodnotes.core import payload as payload_mod
from cli_anything.goodnotes.core import project as project_mod
from cli_anything.goodnotes.core import validate as v
from cli_anything.goodnotes.core.session import Session
from cli_anything.goodnotes.utils import goodnotes_backend as backend

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:gn="http://www.goodnotes.com/gn-svg" '
    'width="100" height="100"><circle cx="50" cy="50" r="40" fill="#336699" stroke="none"/></svg>'
)


@pytest.fixture
def session():
    s = Session()
    project_mod.new_project(s, name="Test")
    return s


class TestMarkdown:
    def test_valid(self):
        assert v.validate_markdown("Notes", "# Hi") == []

    @pytest.mark.parametrize("body", ["", "   \n\t"])
    def test_blank_body_rejected(self, body):
        assert any("empty" in e for e in v.validate_markdown("Notes", body))

    def test_title_limits(self):
        assert v.validate_markdown("x" * 120, "ok") == []
        assert any("120" in e for e in v.validate_markdown("x" * 121, "ok"))
        assert v.validate_markdown("  ", "ok")


class TestSvg:
    def test_valid(self):
        assert v.validate_svg("Dot", GOOD_SVG) == []

    def test_normalize_adds_namespaces(self):
        raw = '<svg width="10" height="10"><rect width="5" height="5" fill="#000000"/></svg>'
        assert v.validate_svg("t", raw)
        assert v.validate_svg("t", v.normalize_svg(raw)) == []

    def test_normalize_is_idempotent(self):
        assert v.normalize_svg(GOOD_SVG) == GOOD_SVG

    def test_normalize_self_closing_root(self):
        out = v.normalize_svg('<svg width="3" height="3"/>')
        assert out.endswith("/>") and "xmlns:gn" in out

    @pytest.mark.parametrize("snippet,needle", [
        ('<linearGradient id="g"/>', "lineargradient"),
        ('<radialGradient id="g"/>', "radialgradient"),
        ('<pattern id="p"/>', "pattern"),
        ('<rect width="2" height="2" fill="#000000" transform="rotate(45)"/>', "rotate"),
        ('<rect width="2" height="2" fill="red"/>', "hex"),
        ('<rect width="2" height="2" fill="url(#g)"/>', "paint server"),
        ('<rect width="2" height="2" style="fill:blue"/>', "hex"),
    ])
    def test_forbidden_constructs(self, snippet, needle):
        svg = GOOD_SVG.replace("</svg>", snippet + "</svg>")
        assert any(needle in e.lower() for e in v.validate_svg("t", svg))

    def test_cdata_rejected(self):
        svg = GOOD_SVG.replace("</svg>", "<text><![CDATA[x]]></text></svg>")
        assert any("CDATA" in e for e in v.validate_svg("t", svg))

    def test_duplicate_attribute_reported_as_malformed(self):
        svg = GOOD_SVG.replace('r="40"', 'r="40" r="41"')
        assert any("well-formed" in e for e in v.validate_svg("t", svg))

    def test_unclosed_tag(self):
        assert any("well-formed" in e for e in v.validate_svg("t", GOOD_SVG.replace("</svg>", "")))

    def test_entity_declarations_rejected(self):
        evil = '<!DOCTYPE s [<!ENTITY a "b">]>' + GOOD_SVG
        assert any("forbidden" in e for e in v.validate_svg("t", evil))

    def test_needs_measurable_bounds(self):
        no_size = GOOD_SVG.replace(' width="100" height="100"', "")
        assert any("viewBox" in e for e in v.validate_svg("t", no_size))
        with_box = no_size.replace("<circle", "<circle").replace(">", ' viewBox="0 0 10 10">', 1)
        assert v.validate_svg("t", with_box) == []
        zero = GOOD_SVG.replace('width="100"', 'width="0"')
        assert v.validate_svg("t", zero)


class TestMermaid:
    FLOW = 'flowchart TD\n  A["Start"] --> B{"Ready?"}'

    def test_valid_each_type(self):
        assert v.validate_mermaid("t", "flowchart", self.FLOW) == []
        assert v.validate_mermaid("t", "flowchart", "graph LR\n  A --> B") == []
        assert v.validate_mermaid("t", "mindmap", 'mindmap\n  root("Plan")\n    a("One")') == []
        assert v.validate_mermaid("t", "timeline", "timeline\n  title Plan\n  2026 : Launch") == []

    def test_unknown_type(self):
        assert any("invalid" in e for e in v.validate_mermaid("t", "sequence", "sequenceDiagram"))

    def test_type_must_match_first_line(self):
        assert any("first line" in e for e in v.validate_mermaid("t", "mindmap", self.FLOW))

    def test_leading_comment_is_skipped(self):
        assert v.validate_mermaid("t", "flowchart", "%% note\n" + self.FLOW) == []

    @pytest.mark.parametrize("bad", ["`code`", "A --> B #tag", "<script>x</script>", "javascript:alert(1)", "click A call f()"])
    def test_forbidden_content(self, bad):
        assert v.validate_mermaid("t", "flowchart", "flowchart TD\n  A --> B\n  " + bad)

    def test_unquoted_special_label(self):
        assert any("quoted" in e for e in v.validate_mermaid("t", "flowchart", "flowchart TD\n  A[Start (now)] --> B"))
        assert v.validate_mermaid("t", "flowchart", "flowchart TD\n  A[Plain words] --> B") == []

    def test_empty(self):
        assert v.validate_mermaid("t", "flowchart", "  ")


class TestOptionChecks:
    def test_background(self):
        assert v.check_background("white", "dotted") == []
        assert v.check_background(None, None) == []
        assert v.check_background("dark", None)
        assert v.check_background(None, "grid")

    def test_theme(self):
        assert v.check_theme("gray", "dark") == []
        assert v.check_theme("neon", None)
        assert v.check_theme(None, "mid")


class TestPayload:
    def test_markdown_payload_uses_schema_names(self, session):
        project_mod.add_markdown(session, "Notes", "# Hi")
        call = payload_mod.build_payload(session.state["items"][0])
        assert call == {"tool": "create_markdown_text_document", "arguments": {"title": "Notes", "rawMarkdown": "# Hi"}}

    def test_optional_fields_omitted_by_default(self, session):
        project_mod.add_svg(session, "Dot", GOOD_SVG)
        project_mod.add_mermaid(session, "Flow", "flowchart", TestMermaid.FLOW)
        svg_call, flow_call = (payload_mod.build_payload(i) for i in session.state["items"])
        assert "background" not in svg_call["arguments"]
        assert "theme" not in flow_call["arguments"] and "background" not in flow_call["arguments"]

    def test_options_included_when_set(self, session):
        project_mod.add_svg(session, "Dot", GOOD_SVG, color="black", pattern="squared")
        project_mod.add_mermaid(session, "Flow", "flowchart", TestMermaid.FLOW, theme_color="gray",
                                theme_shade="dark", color="yellow")
        svg_call, flow_call = (payload_mod.build_payload(i) for i in session.state["items"])
        assert svg_call["arguments"]["background"] == {"color": "black", "pattern": "squared"}
        assert flow_call["arguments"]["theme"] == {"color": "gray", "shade": "dark"}
        assert flow_call["arguments"]["background"] == {"color": "yellow"}
        assert flow_call["arguments"]["diagramType"] == "flowchart"

    def test_invalid_item_refuses_payload(self):
        with pytest.raises(v.ValidationError):
            payload_mod.build_payload({"kind": "markdown", "title": "", "markdown": ""})

    def test_unknown_kind(self):
        assert payload_mod.validate_item({"kind": "pdf"})


class TestProject:
    def test_requires_open_project(self):
        with pytest.raises(RuntimeError, match="No project is open"):
            project_mod.list_items(Session())

    def test_add_assigns_incrementing_ids(self, session):
        a = project_mod.add_markdown(session, "A", "x")
        b = project_mod.add_markdown(session, "B", "y")
        assert (a["id"], b["id"]) == ("item-1", "item-2")

    def test_ids_are_not_reused_after_remove(self, session):
        project_mod.add_markdown(session, "A", "x")
        project_mod.remove_item(session, "item-1")
        assert project_mod.add_markdown(session, "B", "y")["id"] == "item-2"

    def test_invalid_add_does_not_modify_state(self, session):
        before = json.dumps(session.state, sort_keys=True)
        with pytest.raises(v.ValidationError):
            project_mod.add_svg(session, "Bad", "<svg><rect fill='red'/></svg>")
        with pytest.raises(v.ValidationError):
            project_mod.add_svg(session, "Bad bg", GOOD_SVG, color="purple")
        assert json.dumps(session.state, sort_keys=True) == before

    def test_get_unknown_item(self, session):
        with pytest.raises(KeyError, match="item list"):
            project_mod.get_item(session, "item-9")

    def test_info_and_validate(self, session):
        project_mod.add_markdown(session, "A", "x")
        project_mod.add_svg(session, "S", GOOD_SVG)
        info = project_mod.project_info(session)
        assert info["items"] == 2 and info["by_kind"] == {"markdown": 1, "svg": 1}
        assert project_mod.validate_items(session)["valid"]

    def test_mark_submitted_and_select(self, session):
        project_mod.add_markdown(session, "A", "x")
        project_mod.add_markdown(session, "B", "y")
        project_mod.mark_submitted(session, "item-1", {"text": "ok"})
        assert [i["id"] for i in project_mod.select(session, None, include_submitted=False)] == ["item-2"]
        assert len(project_mod.select(session, None, include_submitted=True)) == 2

    def test_slug(self):
        assert project_mod.slug("Hello, World!") == "hello-world"
        assert project_mod.slug("!!!") == "untitled"


class TestSession:
    def test_undo_redo(self, session):
        project_mod.add_markdown(session, "A", "x")
        assert session.undo() and session.state["items"] == []
        assert session.redo() and len(session.state["items"]) == 1
        assert not session.redo()

    def test_new_change_clears_redo(self, session):
        project_mod.add_markdown(session, "A", "x")
        session.undo()
        project_mod.add_markdown(session, "B", "y")
        assert not session.redo()

    def test_save_open_round_trip(self, session, tmp_path):
        project_mod.add_markdown(session, "A", "x")
        path = str(tmp_path / "p.json")
        project_mod.save_project(session, path)
        fresh = Session()
        fresh.open_project(path)
        assert fresh.state == session.state and not fresh.modified

    def test_save_overwrites_without_leftover_bytes(self, session, tmp_path):
        path = str(tmp_path / "p.json")
        project_mod.add_markdown(session, "A", "x" * 5000)
        session.save_project(path)
        project_mod.remove_item(session, "item-1")
        session.save_project(path)
        assert json.load(open(path))["items"] == []

    def test_open_rejects_bad_files(self, tmp_path):
        s = Session()
        with pytest.raises(FileNotFoundError):
            s.open_project(str(tmp_path / "missing.json"))
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            s.open_project(str(bad))
        other = tmp_path / "other.json"
        other.write_text('{"hello": 1}')
        with pytest.raises(ValueError, match="not a Goodnotes project"):
            s.open_project(str(other))


class TestExportFiles:
    def test_writes_sources_and_outbox(self, session, tmp_path):
        project_mod.add_markdown(session, "My Notes", "# Hi")
        project_mod.add_mermaid(session, "Flow", "flowchart", TestMermaid.FLOW)
        project_mod.add_svg(session, "Dot", GOOD_SVG)
        result = project_mod.export_files(session, str(tmp_path / "out"))
        names = sorted(os.path.basename(f["path"]) for f in result["files"])
        assert names == ["item-1-my-notes.md", "item-2-flow.mmd", "item-3-dot.svg"]
        outbox = json.load(open(result["outbox"]))
        assert [o["tool"] for o in outbox] == [
            "create_markdown_text_document", "generate_mermaid_diagram", "draw_svg_image"]

    def test_refuses_to_overwrite(self, session, tmp_path):
        project_mod.add_markdown(session, "A", "x")
        project_mod.export_files(session, str(tmp_path))
        with pytest.raises(FileExistsError):
            project_mod.export_files(session, str(tmp_path))
        project_mod.export_files(session, str(tmp_path), overwrite=True)

    def test_empty_project(self, session, tmp_path):
        with pytest.raises(ValueError, match="Nothing to export"):
            project_mod.export_files(session, str(tmp_path))


class TestBackendConfig:
    def test_unconfigured(self):
        cfg = backend.load_config({})
        assert cfg.transport is None
        status = backend.is_available(cfg)
        assert status["configured"] is False and "GOODNOTES_MCP_URL" in status["message"]

    def test_http_and_stdio_selection(self):
        assert backend.load_config({"GOODNOTES_MCP_URL": "https://mcp.example.com/mcp"}).transport == "http"
        cfg = backend.load_config({"GOODNOTES_MCP_COMMAND": "node", "GOODNOTES_MCP_ARGS": 'server.js --flag "a b"'})
        assert cfg.transport == "stdio" and cfg.args == ["server.js", "--flag", "a b"]

    def test_url_wins_over_command(self):
        cfg = backend.load_config({"GOODNOTES_MCP_URL": "https://x.example/mcp", "GOODNOTES_MCP_COMMAND": "node"})
        assert cfg.transport == "http"

    @pytest.mark.parametrize("url", ["ftp://x.example/mcp", "http://remote.example/mcp", "not a url"])
    def test_rejects_unsafe_urls(self, url):
        with pytest.raises(backend.BackendError):
            backend.load_config({"GOODNOTES_MCP_URL": url})

    def test_loopback_http_allowed(self):
        assert backend.load_config({"GOODNOTES_MCP_URL": "http://127.0.0.1:9/mcp"}).transport == "http"

    def test_bad_timeout(self):
        with pytest.raises(backend.BackendError, match="TIMEOUT"):
            backend.load_config({"GOODNOTES_MCP_TIMEOUT": "soon"})

    def test_describe_never_leaks_token(self):
        cfg = backend.load_config({"GOODNOTES_MCP_URL": "https://x.example/mcp", "GOODNOTES_MCP_TOKEN": "s3cret-value"})
        assert "s3cret-value" not in json.dumps(cfg.describe()) and cfg.describe()["token_set"] is True

    def test_call_without_server_fails_clearly(self):
        with pytest.raises(backend.BackendError, match="No Goodnotes MCP server"):
            backend.call_tool("draw_svg_image", {}, backend.load_config({}))
