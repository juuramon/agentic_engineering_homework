# QA API Test Planner — v2 (SDK variant)

Same three-phase pipeline as the [`no_sdk`](../no_sdk/) sibling, written
the way the **OpenAI Agents SDK** is meant to be used. Point it at an
OpenAPI spec, get a Markdown test plan and a runnable Playwright spec.

The folder is called `sdk_codex/` because the homework brief said "Claude
or Codex SDK." In OpenAI's 2026 stack, Codex (the coding-agent CLI) is
built on the `openai-agents` package — that's the public, stable surface
for custom tool calling. The Codex Python SDK doesn't expose a way to
register your own Python functions as tools, so this variant uses the
Agents SDK directly.

## What's different from `no_sdk/`

The two versions solve the same problem and produce the same artifacts.
What changes is *how*:

| | `no_sdk/` | `sdk_codex/` (this folder) |
|---|---|---|
| HTTP | hand-rolled `urllib.request` | SDK handles it |
| Tool schemas | inline JSON-schema dicts | introspected from function signatures + docstrings |
| Loop | manual `tool_calls` ↔ `tool_call_id` dispatch | `Runner.run(agent, ...)` |
| Structured outputs | `submit_review` tool, args inspected by orchestrator | `output_type=Verdict` Pydantic model; `result.final_output` is the parsed instance |
| Per-run state | module-level globals | `RunContextWrapper` |
| Lines | ~620 | ~410 |

Same prompts, same artifacts. The SDK takes over the plumbing.

## The pipeline

```
Phase 1 — planner    spec        → PlannedReport(slug, markdown)
Phase 2 — review     plan        → Verdict(blocking_issues, suggestions)
         → amend     blockers    → PlannedReport (surgical edit, same slug)
         → review    amended     → Verdict
         ...                       loop until ship condition (see below)
Phase 3 — codegen    plan + lang → GeneratedSpec(code)
```

Each phase is an `Agent[PlannerContext]` with a typed `output_type`. The
orchestrator (`orchestrate()` in `qa_planner.py`) writes files between
phases — the agents return data, not side effects.

## The review/amend loop

The reviewer returns a `Verdict` with **two** lists:

- `blocking_issues` — things that would make the plan wrong or incomplete.
  Capped at 5, ranked by severity.
- `suggestions` — nice-to-have refinements. No cap.

The loop runs in two modes within a single shared `--max-rounds` budget:

1. **`fix_blockers`** — amend until `blocking_issues == []`. Convergence
   guard: if blocker count doesn't drop between rounds, ship anyway (loop
   is stuck).
2. **`polish`** — switch in once blockers are clear. Amend until the
   suggestion count stops strictly decreasing. Tightening that no longer
   tightens is done.

The amender is a separate agent from the planner. It receives the current
plan plus the issues to address and is told to make surgical edits, not
rewrite from scratch. Result: smaller diffs between revisions, faster
convergence, lower token cost.

## What you need

- Python 3.10+
- OpenAI API key
- `uv` (or plain `pip`)

## Setup

```bash
uv venv
uv pip install -r requirements.txt
# OPENAI_API_KEY is read from homework_2/.env (one level up) or from your shell.
```

Dependencies: `openai-agents` (which pulls in `pydantic`) and `PyYAML`.

## Run it

```bash
# default: up to 3 review rounds, Python spec output, gpt-4o-mini
uv run qa_planner.py examples/login.yaml

# TypeScript spec
uv run qa_planner.py --lang typescript examples/petstore.json

# Verbose: phase headers, suggestion lists, mode transitions
uv run qa_planner.py -v --max-rounds 5 examples/login.yaml

# Smoke: planner only, no review, no codegen
uv run qa_planner.py --max-rounds 0 examples/login.yaml
```

Sample log:

```
[plan] saved output/login-api-test-plan.md
[round 1 fix_blockers] blocking=2 suggestions=4
[plan] amended (blocking) → output/login-api-test-plan.md
[round 2 fix_blockers] blocking=0 suggestions=5
[ok] no blocking issues; entering polish mode
[plan] amended (suggestion) → output/login-api-test-plan.md
[round 3 polish] blocking=0 suggestions=2
[ok] suggestion count not decreasing... actually 5 → 2 → ship
[spec] saved output/tests/login-api.spec.py
```

(Your exact rounds will vary — that's the point of the convergence
heuristic.)

## The two tools (only)

Most of the work happens in typed agent outputs, not tool calls. The
planner has two tools; the other phases have none.

| Tool | Used by | Purpose |
|---|---|---|
| `load_api_spec()` | planner | Read + parse the spec at `wrapper.context.spec_path`. |
| `list_endpoints(parsed_spec)` | planner | Flatten OpenAPI `paths` into method/path/summary/codes. |

Note: `load_api_spec` takes no arguments — the spec path comes from
`RunContextWrapper[PlannerContext]`. The model doesn't see the path and
can't be tricked into asking for `/etc/passwd`.

`list_endpoints` uses `strict_mode=False` because the OpenAPI document
shape is too dynamic to schematize strictly. Everything else is strict.

## Typed outputs

```python
class PlannedReport(BaseModel):
    slug: str
    markdown: str

class Verdict(BaseModel):
    blocking_issues: list[str]  # max 5, must-fix
    suggestions: list[str]      # no cap, polish

class GeneratedSpec(BaseModel):
    code: str
```

These drop the no_sdk version's `save_plan`/`submit_review`/`save_spec`
tools entirely. File writes happen in the orchestrator. The model returns
content; Python decides where it goes.

## CLI

```
uv run qa_planner.py [-v] [--lang python|typescript]
                     [--max-rounds N] <spec_file>
```

| Flag | Default | Notes |
|---|---|---|
| `-v` / `--verbose` | off | Phase headers, suggestion list on each round, agent final outputs. |
| `--lang` | `python` | `python` → pytest-playwright, `typescript` → `@playwright/test`. |
| `--max-rounds` | `3` | Shared budget across `fix_blockers` + `polish`. `0` = planner only. |

## Config

| Env var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Required. Read from `homework_2/.env` (shared) or shell. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any model with structured-output + tool support. |

Shell env wins over `.env`. The `.env` loader is a tiny stdlib helper.

## Files

```
qa_planner.py        # agents, prompts, orchestrator, CLI — ~410 lines
examples/            # sample specs (copied from no_sdk for parity)
output/              # generated plans
output/tests/        # generated spec files
requirements.txt     # openai-agents, PyYAML
.venv/               # isolated; gitignored
```

## What this teaches (vs no_sdk)

1. **The SDK earns its keep on structured outputs.** Replacing
   `submit_review` as a tool with `output_type=Verdict` is the biggest
   simplification — one round-trip removed, no JSON-parsing-of-args, the
   verdict arrives as a typed Python object.
2. **Per-run state has a proper home.** `RunContextWrapper` instead of
   module globals. Tools that need run-scoped data ask for it via type
   annotation; the SDK plumbs it through.
3. **Agents are declarative.** `Agent[Ctx](name, instructions, model,
   tools, output_type)` says everything in five fields. The plumbing is
   gone.
4. **Loop control stays in Python.** The model has judgment; Python has
   the `for rnd in range(max_rounds)`. Mixing the two is a recipe for
   non-terminating runs.
