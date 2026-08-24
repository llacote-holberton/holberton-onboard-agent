# JOURNAL.md — Development log (branch `feature/palier5`)

Chronological journal of decisions made during paliers 3 to 5, reconstructed from this branch's Git history (22 commits, Hugo, 08/20-21/2026) and `eval/cases.md`. Goal: keep track of the *why*, not just the *what* — the code and docstrings already say what was done.

## 08/20, morning — Giving the tool catalog an operator-controlled boundary

Until now, any tool registered on the `mcp-server` side was automatically proposable by the agent. First project of the day: introduce `ALLOWED_TOOLS`, an operator-configured allowlist (environment variable), independent of what the model is *technically capable* of proposing.

An important design decision was made at this stage: a disallowed action must **not silently disappear** from the plan. It must remain visible, struck through, with an explanation — so the user always sees the agent's full intent, including the part it isn't allowed to execute. This is the origin of the `excluded_actions` field, distinct from `actions`, which runs through the rest of the project (the `Plan` model, the API response, the Streamlit display).

Concretely, that morning: the MCP resource `config://allowed-tools` (`mcp_server/resources.py`), the `/agent/tools` endpoint on the backend side, the display of excluded actions on the frontend side, and the first filtering of allowed actions in the plan logic.

## 08/20, midday — A plan you can find again

Small but practical standalone project: persisting the current plan's id in the URL (`st.query_params`) rather than only in Streamlit's `session_state`, which gets cleared on any real page reload. Without this, refreshing the page or sharing a link would lose the plan in progress.

## 08/20, afternoon — First drafts of the multi-turn loop

Two commits marked `DRAFT`: `list_teams` (a read-only tool listing the valid teams from the directory) and a first version of multi-turn exploratory execution inside `build_plan`. This is the starting point of palier 4's most structural change: until then, the agent had to decide everything in a single call to the model. The idea tested here — letting the model consult information along the way, over several turns of conversation with itself — would become the core of `planner.py`.

## 08/20, end of afternoon — The multi-turn loop goes into production

The afternoon's draft is reworked into the stable version: `build_plan` now holds a multi-turn conversation with the model (guarded by `_MAX_TURNS`), distinguishes exploratory tools (executed immediately, with no side effect) from action proposals (never executed at this stage, only accumulated), and systematically prompts the model again after each proposal to ask whether it has anything else to add.

The system prompt is rewritten at the same time to reflect this new mode of operation — distinguishing a general intent ("propose whatever you find relevant") from an explicit list of actions ("only propose what was asked for"), and reminding the model that `list_teams` exists to verify a team before acting rather than guessing.

Later that same evening: raising the maximum number of turns, and switching from a generic nudge ("anything else?") to a **targeted** nudge that explicitly names the tools not yet used — a direct fix to a problem observed in practice (see `eval/cases.md`, case 2: `create_calendar_event` was regularly forgotten by the model on a multi-action plan, despite a meeting being explicitly requested; the targeted nudge fixes this). The plan-generation timeout increase goes hand in hand with this change — more turns means more calls to the model, hence more time.

The `generate_handbook` tool (welcome document generation) is also implemented that evening, along with a strengthened validation on `create_employee_record`.

## 08/21, morning — Making failures understandable by a human

First project of the following day: when the model produces a malformed tool call (raw JSON instead of a proper structured call — observed in particular while trying to trigger this case via a prompt manipulation attempt, see `eval/cases.md` case 6), that technical fragment must never land in front of the user as-is. A generic, understandable message now replaces it.

This is the throughline of palier 5, which continues all day: **the user must understand what to do**, never read an error message written for a developer.

## 08/21, afternoon — Observability, reliability, and closing out the tests

A tightly packed series of fixes late in the afternoon:

- **Turn-by-turn trace** exposed all the way into the interface (`plan.trace`, the "🔍 Why this plan?" panel) — until then, the agent's decision sequence was only visible in the Docker logs. The backend/frontend timeouts are revisited at the same time: with the loop now able to run up to 8 turns, the timeout left at 120s on the backend side had become insufficient for a complete plan (a concrete regression documented in `eval/cases.md`, case 2 — fixed by aligning the backend timeout to 240s and the frontend one to 260s).
- **Cleanup of the technical FastMCP prefix** (`Error calling tool '...':`) on error messages surfaced to the user (`executor.py::_humanize_error`) — the same logic as in the morning, applied this time to execution errors rather than malformed calls.
- **Model warmup on agent startup**, and enrichment of the plan response structure.
- **Clearer error message** for an unknown department/team, and addition of `eval/cases.md` — the file that documents, case by case, what has been tested and its last known result.
- **Porting of compatible tests from `dev_laurent`** — a parallel branch of the project, from which some tests (on tools whose core logic stayed identical) could be pulled over as-is rather than rewritten.
- Latest commit on the branch to date: one more pass on error message clarity, this time on the `/plans` and `/execute` endpoints themselves.

## Status as of 08/21

`eval/cases.md` lists 7 end-to-end scenarios; 6 pass, the 7th (execution guardrail without prior exploration) is partially validated — it still needs `send_welcome_message` to be temporarily re-allowed to confirm the clean execution failure with a nonsensical team, not just the absence of exploration. See `AGENTS.md` for an explanation of the agent's current behavior from the user's side, and `eval/cases.md` for the case-by-case detail.

## How to keep this journal up to date

One entry per significant work session, not per commit: the *why* behind a behavior change (a new guardrail, a fixed regression, a deliberate design decision) — not a mechanical list of touched files, which `git log` already does perfectly well.
