# TEST.md: cli-anything-goodnotes

## Test plan

### `test_core.py`: unit tests (synthetic data, no server)
- **Markdown validation**: blank body, title limits (120 / 121 / whitespace).
- **SVG validation**: valid document; namespace normalization (idempotent, self-closing root); each forbidden
  construct (linear/radial gradient, pattern, rotate, named color, `url()` paint, CSS `style` color, CDATA);
  duplicate attribute; unclosed tag; DOCTYPE/entity declarations; missing, zero or viewBox-only bounds.
- **Mermaid validation**: each diagram type; unknown type; first line must match type; leading `%%` comment;
  backtick, hash, script, `javascript:`, `click`; unquoted special-character labels; empty code.
- **Option checks**: background color/pattern, theme color/shade.
- **Payload**: argument names match the tool schemas; optional fields omitted unless set; invalid items refused.
- **Project / session**: ids increment and are never reused, failed adds leave state untouched, undo/redo,
  save/open round trip, overwrite leaves no stale bytes, bad files rejected, export files and outbox.
- **Backend config**: transport selection, URL safety, timeout parsing, token never described, no-server error.

### `test_full_e2e.py`: subprocess and protocol tests
- **CLI subprocess** (installed command via `_resolve_cli`): help/version, `--json` lifecycle, add/list/remove,
  `--dry-run`, validation failures (text and JSON), source-argument misuse, stdin input, standalone `validate`,
  `export payload` against the tool schemas, `export files` (artifact paths printed), `send` with no server.
- **MCP over stdio**: `backend status` lists the three tools; `send` delivers exact arguments and marks items
  submitted; a second `send` has nothing to do and `--all` resends; a server-side error stops the batch and
  leaves later items draft; an unreachable command reports an error and changes nothing.
- **MCP over streamable HTTP** (localhost): status and send with a bearer token configured, token not leaked.

### Workflows
- **Study notes pack**: markdown note + themed flowchart + dark-background SVG, validated, exported, sent.
- **Partial failure**: three notes, the second rejected by the server; first submitted, others stay draft.

## What these tests do and do not prove

The server in these tests is `fake_goodnotes_server.py`, a stand-in with the same tool names, argument names
and enum values as the Goodnotes tools. It checks only a few basic rules and renders nothing.
The tests prove the harness builds correct tool calls and handles the MCP protocol, errors and state correctly.
They do **not** prove that the hosted Goodnotes service accepts a given piece of content, or how it looks in the
app. That needs a run against a real Goodnotes MCP endpoint, which was not available when this was written.

## Test results

Command: `CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/goodnotes/tests -v`

```
test_core.py::TestMarkdown::test_valid PASSED
test_core.py::TestMarkdown::test_blank_body_rejected[] PASSED
test_core.py::TestMarkdown::test_blank_body_rejected[   \n\t] PASSED
test_core.py::TestMarkdown::test_title_limits PASSED
test_core.py::TestSvg::test_valid PASSED
test_core.py::TestSvg::test_normalize_adds_namespaces PASSED
test_core.py::TestSvg::test_normalize_is_idempotent PASSED
test_core.py::TestSvg::test_normalize_self_closing_root PASSED
test_core.py::TestSvg::test_forbidden_constructs[<linearGradient id="g"/>-lineargradient] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<radialGradient id="g"/>-radialgradient] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<pattern id="p"/>-pattern] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<rect width="2" height="2" fill="#000000" transform="rotate(45)"/>-rotate] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<rect width="2" height="2" fill="red"/>-hex] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<rect width="2" height="2" fill="url(#g)"/>-paint server] PASSED
test_core.py::TestSvg::test_forbidden_constructs[<rect width="2" height="2" style="fill:blue"/>-hex] PASSED
test_core.py::TestSvg::test_cdata_rejected PASSED
test_core.py::TestSvg::test_duplicate_attribute_reported_as_malformed PASSED
test_core.py::TestSvg::test_unclosed_tag PASSED
test_core.py::TestSvg::test_entity_declarations_rejected PASSED
test_core.py::TestSvg::test_needs_measurable_bounds PASSED
test_core.py::TestMermaid::test_valid_each_type PASSED
test_core.py::TestMermaid::test_unknown_type PASSED
test_core.py::TestMermaid::test_type_must_match_first_line PASSED
test_core.py::TestMermaid::test_leading_comment_is_skipped PASSED
test_core.py::TestMermaid::test_forbidden_content[`code`] PASSED
test_core.py::TestMermaid::test_forbidden_content[A --> B #tag] PASSED
test_core.py::TestMermaid::test_forbidden_content[<script>x</script>] PASSED
test_core.py::TestMermaid::test_forbidden_content[javascript:alert(1)] PASSED
test_core.py::TestMermaid::test_forbidden_content[click A call f()] PASSED
test_core.py::TestMermaid::test_unquoted_special_label PASSED
test_core.py::TestMermaid::test_empty PASSED
test_core.py::TestOptionChecks::test_background PASSED
test_core.py::TestOptionChecks::test_theme PASSED
test_core.py::TestPayload::test_markdown_payload_uses_schema_names PASSED
test_core.py::TestPayload::test_optional_fields_omitted_by_default PASSED
test_core.py::TestPayload::test_options_included_when_set PASSED
test_core.py::TestPayload::test_invalid_item_refuses_payload PASSED
test_core.py::TestPayload::test_unknown_kind PASSED
test_core.py::TestProject::test_requires_open_project PASSED
test_core.py::TestProject::test_add_assigns_incrementing_ids PASSED
test_core.py::TestProject::test_ids_are_not_reused_after_remove PASSED
test_core.py::TestProject::test_invalid_add_does_not_modify_state PASSED
test_core.py::TestProject::test_get_unknown_item PASSED
test_core.py::TestProject::test_info_and_validate PASSED
test_core.py::TestProject::test_mark_submitted_and_select PASSED
test_core.py::TestProject::test_slug PASSED
test_core.py::TestSession::test_undo_redo PASSED
test_core.py::TestSession::test_new_change_clears_redo PASSED
test_core.py::TestSession::test_save_open_round_trip PASSED
test_core.py::TestSession::test_save_overwrites_without_leftover_bytes PASSED
test_core.py::TestSession::test_open_rejects_bad_files PASSED
test_core.py::TestExportFiles::test_writes_sources_and_outbox PASSED
test_core.py::TestExportFiles::test_refuses_to_overwrite PASSED
test_core.py::TestExportFiles::test_empty_project PASSED
test_core.py::TestBackendConfig::test_unconfigured PASSED
test_core.py::TestBackendConfig::test_http_and_stdio_selection PASSED
test_core.py::TestBackendConfig::test_url_wins_over_command PASSED
test_core.py::TestBackendConfig::test_rejects_unsafe_urls[ftp://x.example/mcp] PASSED
test_core.py::TestBackendConfig::test_rejects_unsafe_urls[http://remote.example/mcp] PASSED
test_core.py::TestBackendConfig::test_rejects_unsafe_urls[not a url] PASSED
test_core.py::TestBackendConfig::test_loopback_http_allowed PASSED
test_core.py::TestBackendConfig::test_bad_timeout PASSED
test_core.py::TestBackendConfig::test_describe_never_leaks_token PASSED
test_core.py::TestBackendConfig::test_call_without_server_fails_clearly PASSED
test_full_e2e.py::TestCLISubprocess::test_help_and_version PASSED
test_full_e2e.py::TestCLISubprocess::test_json_project_lifecycle PASSED
test_full_e2e.py::TestCLISubprocess::test_add_list_remove PASSED
test_full_e2e.py::TestCLISubprocess::test_dry_run_does_not_save PASSED
test_full_e2e.py::TestCLISubprocess::test_invalid_content_fails_with_reasons PASSED
test_full_e2e.py::TestCLISubprocess::test_rejects_both_or_neither_source PASSED
test_full_e2e.py::TestCLISubprocess::test_content_from_stdin PASSED
test_full_e2e.py::TestCLISubprocess::test_standalone_validate PASSED
test_full_e2e.py::TestCLISubprocess::test_export_payload_matches_tool_schemas PASSED
test_full_e2e.py::TestCLISubprocess::test_export_files PASSED
test_full_e2e.py::TestCLISubprocess::test_send_without_server_fails_clearly_and_changes_nothing PASSED
test_full_e2e.py::TestCLISubprocess::test_backend_status_unconfigured PASSED
test_full_e2e.py::TestMcpStdio::test_status_lists_the_three_tools PASSED
test_full_e2e.py::TestMcpStdio::test_send_delivers_exact_arguments_and_marks_submitted PASSED
test_full_e2e.py::TestMcpStdio::test_server_error_stops_send_and_keeps_later_items_draft PASSED
test_full_e2e.py::TestMcpStdio::test_unreachable_server_reports_error PASSED
test_full_e2e.py::TestMcpHttp::test_send_over_streamable_http PASSED
============================= 81 passed in 17.62s ==============================
```

## Summary

- 81 tests: 64 unit (`test_core.py`), 17 end-to-end (`test_full_e2e.py`). All passed.
- Not covered: a run against a real Goodnotes MCP server; the interactive REPL beyond a manual smoke test.
