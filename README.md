# Homeworks

My submissions for the vibe coding course. One folder per assignment.

## [`homework_1/`](./homework_1) — QA API Test Planner (CLI)

A small Python CLI that takes an OpenAPI/Swagger spec (or a freeform `.md`
note) and asks an LLM to draft a Markdown test plan for it. The point of
the exercise was the **tool-calling loop**: three Python functions
(`load_api_spec`, `list_endpoints`, `save_report`) are exposed as tools and
the model decides when to call them. Stdlib + `PyYAML`, ~190 lines.

## [`homework_2/`](./homework_2) — My Claude Code setup

Not a script — my actual Claude Code configuration. Permissions, a
`block-secrets` PreToolUse hook, three agents (`commit-and-pr`,
`test-designer`, `test-automation-guide`), a few skills, and the MCP
servers I use (context7, playwright). Meant to be readable as a reference
for how I've wired things up.

## [`homework_3/`](./homework_3) — QA API Test Planner v2 (two variants)

Same idea as homework 1, but extended into a four-phase pipeline
(plan → review → amend → codegen) that also emits a runnable Playwright
spec. Shipped as **two implementations of the same pipeline** so you can
diff them:

- `no_sdk/` — hand-rolled against the OpenAI HTTP API (~620 lines).
- `sdk_codex/` — same pipeline on the OpenAI Agents SDK (~410 lines).

The delta between the two is the lesson.
