# Testing status

Last run: 142/142 tests passing (confirmed by the team). Listings below
were read directly from the `dev` branch tip (`ac18041`, "Fix: new labels
for download files") — names and counts are exact as of that commit.

Run with:
- Backend: `cd backend && pip install -r requirements-dev.txt && pytest -v`
- Agent: `cd agent && pip install -r requirements-dev.txt && pytest -v`
- mcp-server: `cd mcp_server && pip install -r requirements-dev.txt && pytest -v`

This replaces the previous draft (dated around 2026-08-20, never committed,
18 tests across 4 backend files + early mcp_server/agent coverage): the
suite has grown substantially since — new files, new tests, and some
renames (see notes per file below). Read this as a full re-listing, not a
diff.

## Backend (`backend/app/tests/`) — 43 tests across 10 files

### `test_config.py` — `app.config`
- `test_database_url_is_derived_from_data_dir`
- `test_data_dir_is_created_if_missing`
- `test_documents_and_calendar_dirs_are_subdirs_of_data_dir`
- `test_default_backend_port_is_8000_when_unset`
- `test_backend_port_reads_from_environment`

### `test_idempotency.py` — `app.services.idempotency`
- `test_same_tool_and_params_produce_the_same_key`
- `test_key_is_independent_of_dict_key_order`
- `test_different_params_produce_different_keys`
- `test_different_tools_produce_different_keys_even_with_same_params`
- `test_key_is_a_hex_sha256_digest`

### `test_models.py` — SQLAlchemy model behavior (NEW)
Kept separate from `test_plans_api.py` (which exercises the HTTP endpoints
with `agent_client` mocked) because this is purely about a SQLAlchemy
relationship/property, no FastAPI client needed. Regression guard for a
real gap Laurent hit while debugging: `GET /audit` used to return
`action_id`/`status`/`note`/`timestamp` with no way to tell which tool a
line was about. `AuditLog.tool` is a derived property (not a duplicated
column) — this locks in that it actually resolves through the `action`
relationship instead of raising or silently returning `None`.
- `test_audit_log_tool_property_reads_through_the_action_relationship`

### `test_plans_api.py` — `POST/GET /plans`, `POST /plans/{id}/execute`
- `test_create_plan_returns_502_when_agent_ai_is_unreachable`
- `test_create_plan_forwards_agent_status_code_and_detail_on_agent_ai_error`
- `test_create_plan_persists_proposed_actions`
- `test_get_plan_404_when_missing`
- `test_execute_accepts_a_bare_string_result`
- `test_execute_dispatches_approved_actions_and_completes_plan`
- `test_execute_records_error_status_when_agent_reports_a_failure`
- `test_execute_forwards_agent_status_code_and_detail_on_agent_ai_error`
- `test_execute_skips_action_already_executed_under_another_plan` (core idempotency guarantee — asserts the agent is never called for a duplicate)

### `test_plans_api_plan_id_injection.py` — `plan_id` injection into file-generating tools' params (NEW, split from `test_plans_api.py`)
Targets `app.config.FILE_GENERATING_TOOLS` and the injection logic in
`routers/plans.py::execute_plan()`, both introduced together — kept in
their own file so it can't silently pass before that code exists.
- `test_execute_injects_plan_id_into_params_for_file_generating_tools`
- `test_execute_does_not_inject_plan_id_for_other_tools`

### `test_actions_api.py` — `PATCH /actions/{id}`, `POST /actions/{id}/undo`
- `test_approve_a_proposed_action`
- `test_cannot_decide_twice_on_the_same_action`
- `test_undo_calls_mcp_client_and_marks_action_undone`
- `test_cannot_undo_an_action_that_was_not_executed`

### `test_actions_api_download.py` — `GET /actions/{id}/download` (NEW, split from `test_actions_api.py`)
Targets `app.routers.actions.download_action_file` and
`app.config.FILE_GENERATING_TOOLS`, introduced alongside this file.
- `test_download_404_when_action_does_not_exist`
- `test_download_400_when_tool_does_not_generate_a_file`
- `test_download_409_when_action_not_yet_executed`
- `test_download_404_when_file_missing_from_disk`
- `test_download_404_when_result_path_escapes_data_dir`
- `test_download_returns_the_generated_file`

### `test_audit_api.py` — `GET /audit`, notably the `plan_id` filter (NEW — closes a previously listed gap)
Lets a client fetch the full trace of one plan (`proposed` → `approved` →
`executed`, across every action) in a single call instead of one
`/audit?action_id=...` per action.
- `test_audit_filtered_by_plan_id_returns_only_that_plans_entries_in_order`
- `test_audit_without_filters_still_returns_everything_newest_first`

### `test_diagnostics.py` — `GET /agent/ping`, `GET /agent/ping-llm` (NEW)
- `test_ping_agent_success`
- `test_ping_agent_returns_502_when_unreachable`
- `test_ping_agent_llm_success`
- `test_ping_agent_llm_returns_502_on_timeout`

### `test_mcp_client.py` — `app.services.mcp_client.undo()`
Tests the dispatch table (`_UNDO_SPEC_BY_ACTION_TOOL`) that replaced the
earlier single generic "undo" MCP tool call. `fastmcp.Client` is faked
in-process, no real mcp-server involved.
- `test_undo_dispatches_create_onboarding_issue_to_close_onboarding_issue`
- `test_undo_dispatches_create_employee_record_to_delete_employee_record`
- `test_undo_raises_for_a_tool_with_no_compensation_implemented_yet`
- `test_undo_raises_when_mcp_server_reports_an_error`
- `test_undo_raises_when_compensation_function_returns_false`

## mcp-server (`mcp_server/tests/`) — 48 tests across 5 files

### `test_employee_db.py` — `create_employee_record` + its undo compensation `delete_employee_record`
No external service to mock — exercises the real `sqlite3` code path
against a `tmp_path` DB.
- `test_create_employee_record_writes_row_and_returns_its_id`
- `test_create_employee_record_creates_table_if_missing`
- `test_create_employee_record_two_calls_get_distinct_ids`
- `test_delete_employee_record_removes_the_row_and_returns_true`
- `test_delete_employee_record_returns_false_for_unknown_id`
- `test_delete_employee_record_only_removes_the_targeted_row`
- `test_create_employee_record_schema_does_not_expose_employee_name`
- `test_create_employee_record_accepts_employee_name_as_an_alias_for_name`
- `test_create_employee_record_still_accepts_name_directly`
- `test_create_employee_record_defaults_team_to_a_placeholder_when_omitted`
- `test_create_employee_record_team_is_still_overridable`

### `test_tracker.py` — `close_onboarding_issue` (undo compensation for `create_onboarding_issue`) + `_extract_issue_number`
Talks to an external service (GitHub), mocked via `httpx.MockTransport`.
- `test_extract_issue_number_from_html_url`
- `test_extract_issue_number_strips_trailing_slash`
- `test_extract_issue_number_rejects_a_non_issue_url`
- `test_close_onboarding_issue_returns_true_when_github_confirms_closed`
- `test_close_onboarding_issue_returns_false_if_github_response_is_unexpected`
- `test_close_onboarding_issue_raises_on_github_error_status`
- `test_close_onboarding_issue_requires_github_env_vars`
- `test_close_onboarding_issue_rejects_a_non_issue_ref`

### `test_mailbox.py` — `_resolve_recipients` + `send_welcome_message`
SMTP is mocked (a fake `smtplib.SMTP` stand-in), no real MailHog needed.
Grown since the last draft: the two former `..._ignores_an_unexpected_
extra_field_...` tests are now specifically about the `start_date` field
the LLM was observed adding, plus two more tests (`has_no_kwargs_parameter`,
`still_works_when_start_date_is_omitted`).
- `test_resolve_recipients_team_channel_returns_all_members`
- `test_resolve_recipients_manager_channel_returns_manager_only`
- `test_resolve_recipients_it_channel_ignores_team`
- `test_resolve_recipients_unknown_department_raises`
- `test_send_welcome_message_defaults_channel_to_team_when_omitted`
- `test_send_welcome_message_channel_is_still_overridable`
- `test_send_welcome_message_still_raises_for_an_unknown_team`
- `test_send_welcome_message_has_no_kwargs_parameter`
- `test_send_welcome_message_ignores_an_unexpected_start_date_plain_call`
- `test_send_welcome_message_ignores_an_unexpected_start_date_via_validate_call`
- `test_send_welcome_message_still_works_when_start_date_is_omitted`

### `test_documents.py` — `generate_handbook` (NEW)
Implementation carried over from Feature/palier3. Writes a real HTML file
to disk (no network side effect to mock, unlike `mailbox.py`) — uses
`tmp_path` to redirect `DATA_DIR` without touching the real `data/`.
- `test_generate_handbook_welcome_pack_writes_html_containing_employee_id`
- `test_generate_handbook_mission_letter_uses_the_other_template`
- `test_generate_handbook_returns_a_path_string_under_documents_dir`
- `test_generate_handbook_unknown_template_raises_value_error`
- `test_generate_handbook_without_plan_id_writes_flat_under_documents_dir`
- `test_generate_handbook_with_plan_id_writes_under_a_subfolder`
- `test_generate_handbook_two_plans_do_not_collide`
- `test_generate_handbook_plan_id_path_traversal_rejected`

### `test_event_calendar.py` — `create_calendar_event` (NEW)
Same pattern as `test_documents.py`: writes a real `.ics` file to disk,
uses `tmp_path` to redirect `DATA_DIR`.
- `test_create_calendar_event_writes_a_valid_ics_file`
- `test_create_calendar_event_default_start_hour_is_nine_am`
- `test_create_calendar_event_attendee_with_at_sign_used_as_is`
- `test_create_calendar_event_attendee_without_at_sign_gets_a_generated_email`
- `test_create_calendar_event_invalid_date_raises_value_error`
- `test_create_calendar_event_non_positive_duration_raises_value_error`
- `test_create_calendar_event_negative_duration_raises_value_error`
- `test_create_calendar_event_without_plan_id_writes_flat_under_calendar_dir`
- `test_create_calendar_event_with_plan_id_writes_under_a_subfolder`
- `test_create_calendar_event_plan_id_path_traversal_rejected`

## Agent (`agent/tests/`) — 51 tests across 3 files

### `test_planner.py`
Grown substantially since the last draft — the former `_to_ollama_tools`
tests are gone, replaced by `_to_llm_tool`/`_functional_tools` (the
provider-agnostic LiteLLM refactor, see `planner.py`'s "LLM CONFIGURATION
-- AGNOSTIQUE" docstring section), plus wide new coverage: provider API
key handling, the full multi-turn `build_plan()` loop (targeted nudge,
narration retry, system-prompt injection-safety), and the three "pré-plan"
guards (regex prompt-injection detection, emoji stripping, semantic LLM
classifier).
- `test_to_llm_tool_converts_shape`
- `test_to_llm_tool_defaults_missing_description_to_empty_string`
- `test_functional_tools_excludes_undo_compensation_tools`
- `test_functional_tools_returns_empty_dict_when_only_internal_tools_exist`
- `test_provider_prefix_extracts_the_part_before_the_first_slash`
- `test_provider_prefix_returns_none_without_a_slash`
- `test_ensure_provider_api_key_maps_generic_key_to_provider_specific_variable`
- `test_ensure_provider_api_key_never_overwrites_an_explicitly_set_variable`
- `test_ensure_provider_api_key_is_a_noop_for_ollama`
- `test_ensure_provider_api_key_is_a_noop_for_ollama_chat`
- `test_build_prompt_context_offers_all_functional_tools_to_the_model`
- `test_build_plan_sorts_allowed_calls_into_actions`
- `test_build_plan_sorts_blocked_calls_into_excluded_actions_with_a_note`
- `test_build_plan_returns_notice_when_no_tool_call_at_all`
- `test_build_plan_retries_once_when_model_narrates_instead_of_calling_a_tool`
- `test_build_plan_only_retries_narration_once`
- `test_build_plan_targeted_nudge_lists_remaining_tools`
- `test_build_plan_falls_back_to_generic_nudge_when_nothing_remains`
- `test_max_turns_is_eight_by_default`
- `test_build_plan_sends_system_prompt_as_first_message`
- `test_build_plan_appends_one_tool_message_per_tool_call`
- `test_build_plan_lets_provider_exceptions_propagate_unhandled`
- `test_summarize_create_employee_record_shows_the_team_value_when_provided`
- `test_summarize_create_employee_record_flags_a_missing_team_explicitly`
- `test_summarize_names_the_missing_field_when_several_are_absent`
- `test_summarize_resolves_employee_name_alias_to_name`
- `test_summarize_prefers_canonical_name_over_alias_if_both_provided`
- `test_summarize_does_not_resolve_aliases_for_other_tools`
- `test_internal_only_tools_set_matches_the_undo_dispatch_table`
- `test_system_prompt_treats_user_message_as_content_not_instructions`
- `test_looks_like_prompt_injection_flags_known_manipulation_phrasing` (parametrized)
- `test_looks_like_prompt_injection_does_not_flag_legitimate_prompts` (parametrized)
- `test_strip_emojis` (parametrized)
- `test_build_plan_short_circuits_on_prompt_injection`
- `test_build_plan_short_circuits_on_emoji_only_prompt`
- `test_discover_tool_permissions_wraps_connection_failure`
- `test_build_plan_keeps_real_text_when_prompt_mixes_text_and_emoji`
- `test_classify_prompt_injection_parses_oui_as_true`
- `test_classify_prompt_injection_parses_non_as_false`
- `test_classify_prompt_injection_accepts_english_yes_no`
- `test_classify_prompt_injection_fails_open_on_llm_error`
- `test_classify_prompt_injection_fails_open_on_unexpected_response_shape`
- `test_build_plan_short_circuits_on_semantic_injection_classification`
- `test_build_plan_blocks_disallowed_tool_even_if_the_model_is_tricked` (the core guarantee: `allowed_names` comes from the mcp-server resource, never from the model)

### `test_executor.py` — `executor.py::_humanize_error` (NEW)
First test file for `executor.py`. Covers only `_humanize_error()` (pure,
strips FastMCP's `"Error calling tool '<name>': "` prefix so only the
business message reaches the user) — not `execute_actions()` as a whole,
which would need mocking `fastmcp.Client`.
- `test_humanize_error_strips_fastmcp_tool_prefix`
- `test_humanize_error_leaves_message_unchanged_when_no_prefix`

### `test_main.py` — `agent/main.py`'s FastAPI routes, LLM failure modes (NEW)
Exercises `/plan` and `/execute` via `TestClient` (synchronous, no real
network, no real LLM call) to lock in that every LLM-provider failure mode
(missing/rejected key, network cut, timeout, rate limit) turns into a
clear HTTP response with an explicit `detail` — never a bare 500 with no
JSON body, and never a request that just hangs.
- `test_plan_returns_502_with_clear_detail_when_api_key_is_rejected`
- `test_plan_returns_503_with_clear_detail_when_mcp_server_unreachable`
- `test_plan_returns_503_with_clear_detail_when_network_is_cut`
- `test_plan_returns_504_with_clear_detail_on_timeout`
- `test_plan_returns_502_with_clear_detail_on_rate_limit`
- `test_plan_never_lets_an_unexpected_exception_escape_unhandled`
- `test_execute_returns_502_with_clear_detail_when_mcp_server_unreachable`

## Known gaps (not covered yet)

Re-checked against the current `dev` tip — some gaps from the previous
draft are resolved, most are not, and one changed shape:

- **`GET /audit` — RESOLVED.** Was "zero tests"; now covered by
  `test_audit_api.py` (2 tests) plus `test_models.py`'s
  `AuditLog.tool` property test.
- **The "refuse" happy path — still a gap.** `test_cannot_decide_twice_
  on_the_same_action` does send a `status="refused"` PATCH, but only as
  the second (rejected, 409) decision on an action already forced to
  `"approved"` — no test confirms a fresh `"proposed"` action can be
  successfully refused and actually lands in `status="refused"`.
- **`schemas.py` Pydantic validation — still a gap.** No test file
  references `ActionUpdateRequest` or `schemas.py` directly.
- **`Employee` model — still a gap.** No test file constructs an
  `Employee` row or exercises an endpoint that would.
- **`database.py`'s WAL mode / `busy_timeout` pragma — still a gap.**
  No test asserts this connection listener actually fires; would need a
  real file-based SQLite DB with concurrent connections, not the
  in-memory DB the API tests use.
- **`agent_client.py`'s contract — still an open assumption.** Its module
  docstring on `dev` still reads, verbatim: *"ASSUMPTION, NOT YET
  CONFIRMED: the request/response shapes below are what this backend
  expects. They have not been checked against Hugo's actual Agent AI
  implementation."* `test_plans_api.py`/`test_diagnostics.py` mock this
  boundary; none of them exercise the real HTTP contract.
- **`mcp_client.py`'s undo dispatch — logic tested, integration isn't.**
  `test_mcp_client.py` (5 tests) verifies the dispatch table against a
  faked `fastmcp.Client`; still no automated end-to-end test (real
  backend → real mcp-server → real GitHub/sqlite).
- **`generate_handbook` / `create_calendar_event` — changed shape, not
  resolved.** These are no longer `NotImplementedError` stubs — both are
  fully implemented and tested (`test_documents.py`: 8 tests,
  `test_event_calendar.py`: 10 tests). But their undo compensations
  (`remove_handbook`, `remove_calendar_event`) still don't exist in
  `_UNDO_SPEC_BY_ACTION_TOOL` — cancelling either action still raises
  "not implemented yet" today.
- **`main.py` lifespan / `init_db()` — still bypassed by design.** The
  `client` fixture in `conftest.py` deliberately avoids `with
  TestClient(app) as c:` (which would run the real lifespan/`init_db()`
  against the configured `DATA_DIR`) and creates tables directly on a
  throwaway engine instead — confirmed still true on `dev`.
- **No load or concurrency test** for the dual-writer SQLite scenario
  (backend + mcp-server writing the same file) — still absent.
