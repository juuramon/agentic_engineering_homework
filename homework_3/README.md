# QA API Test Planner — v2 (two variants)

Point either variant at an OpenAPI spec and get a Markdown test plan plus a
runnable Playwright spec file. The pipeline has three phases:

```
spec  →  Planner       →  Markdown test plan
         Reviewer       →  blocking_issues + suggestions
         Amender        →  surgical revision (loops with reviewer)
         Codegen        →  Playwright spec (Python or TypeScript)
```

The homework brief asked us to use "Claude or Codex SDK." This folder
contains **two implementations of the same pipeline** so you can read them
side-by-side and see what the SDK actually buys you.

## The two variants

### [`no_sdk/`](./no_sdk/) — hand-rolled, stdlib + PyYAML

Direct HTTP to OpenAI's Chat Completions endpoint via `urllib`. Manual
tool dispatch loop. Manual JSON schemas for the tools. Manual matching of
`tool_calls` to `tool_call_id` on the way back. Single file, ~620 lines.

Read this first — it shows the wire protocol you'd otherwise never see.

### [`sdk_codex/`](./sdk_codex/) — OpenAI Agents SDK (the underlying surface of the Codex CLI)

Same pipeline, written the way the SDK is meant to be used:

- Agents declared with `Agent[Ctx](name, instructions, model, tools,
  output_type)`.
- Typed outputs via Pydantic models (`PlannedReport`, `Verdict`,
  `GeneratedSpec`) — no `submit_review` / `save_plan` / `save_spec` tools
  needed.
- Per-run state through `RunContextWrapper`, no module globals.
- Smarter review loop: distinguishes blocking issues from polish
  suggestions, amends surgically instead of regenerating, exits when
  improvement plateaus.

Single file, ~410 lines.

The folder is called `sdk_codex/` to match the homework brief. Under the
hood it uses `openai-agents`, which is the public, stable surface that
Codex (the coding-agent CLI) is built on. The Codex Python SDK itself
doesn't expose a public API for registering custom Python functions as
tools, so the Agents SDK is the right hook for what this homework needs.

## Comparison at a glance

| | `no_sdk/` | `sdk_codex/` |
|---|---|---|
| LOC | ~620 | ~410 |
| Deps | `PyYAML` | `openai-agents`, `PyYAML` |
| HTTP | hand-rolled `urllib` | SDK |
| Tools | 5 (incl. `save_plan`, `submit_review`, `save_spec`) | 2 (only `load_api_spec`, `list_endpoints`) |
| Structured outputs | tool call args parsed by orchestrator | `output_type=PydanticModel`, returned as typed objects |
| Per-run state | module globals (`_PLAN_STATE`, etc.) | `RunContextWrapper[PlannerContext]` |
| Review loop | binary `approved` flag | `blocking_issues` + `suggestions`, amend-style, two-mode convergence |

Both variants produce the same artifacts (Markdown plan + Playwright
spec). Both work against the same example specs in their respective
`examples/` folders. Run either one, get the same kind of output.

## Setup

Both variants read `OPENAI_API_KEY` from a `.env` file. The simplest setup:

```bash
cp .env.example .env       # paste your key
```

That single `.env` at this directory level is read by **both** variants —
they fall back to it if their own per-variant `.env` isn't present. If
you want a variant to use a different key or model, drop a `.env` inside
that variant's folder (see each variant's `.env.example`).

Then pick a variant and follow its README:

```bash
cd no_sdk     && cat README.md      # or
cd sdk_codex  && cat README.md
```

Each variant has its own `requirements.txt` and (for `sdk_codex/`) its
own `.venv/` — they're independent projects under one roof.

## Picking one

- **Learning what tool-calling looks like at the protocol level:**
  `no_sdk/`. You'll see every `tool_calls` array, every `tool_call_id`
  match-up, every JSON schema. No magic.
- **Writing real production code:** `sdk_codex/`. The plumbing is gone;
  what's left is intent.
- **For this homework:** read both. The diff between them is the lesson.

## Files

```
homework_2/
├── README.md            # this file
├── .env.example         # shared template (both variants fall back here)
├── .env                 # (gitignored) your real key
├── .gitignore
│
├── no_sdk/              # variant 1 — hand-rolled
│   ├── qa_planner.py
│   ├── README.md
│   ├── requirements.txt
│   ├── examples/
│   └── output/          # generated artifacts (kept in git for demo)
│
└── sdk_codex/           # variant 2 — OpenAI Agents SDK
    ├── qa_planner.py
    ├── README.md
    ├── requirements.txt
    ├── .env.example     # per-variant override template
    ├── examples/
    └── output/
```
