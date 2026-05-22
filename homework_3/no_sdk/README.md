# QA API Test Planner — v2 (planner → reviewer → codegen)

Point it at an OpenAPI spec; get a Markdown test plan and a runnable
Playwright spec file. Same OpenAI Chat Completions API as v1, still
stdlib + PyYAML, still one file.

The new thing in v2 is the **orchestration**: one model plays three roles
in sequence, with a reviewer loop in the middle.

## The three phases

```
Phase 1 — planner    spec        → Markdown test plan
Phase 2 — reviewer   plan        → {approved, issues}; loop revises
Phase 3 — codegen    plan + lang → Playwright spec file
```

Each phase has its own system prompt and its own `messages` list. They
hand off via plain text (the Markdown plan) — not by sharing conversation
history. That keeps each role focused.

### Reviewer = structured tool call

The reviewer doesn't say "LGTM" or "needs work" in prose. It calls
**`submit_review(approved: bool, issues: [str])`** with typed args. The
orchestrator reads those args to decide whether to stop. No string
parsing, no "did it mean yes?" guessing.

If the reviewer never approves within `--max-rounds`, the script logs a
warning and **still proceeds to codegen** with the latest revision. The
homework is about seeing the loop run, not blocking on a perfectionist
reviewer.

## What you need

- Python 3.10+
- OpenAI API key
- `uv` (or plain `pip`)

## Setup

```bash
cp .env.example .env       # paste your OPENAI_API_KEY=sk-...
uv venv
uv pip install -r requirements.txt
```

Only dependency: `PyYAML`. HTTP, JSON, env loading are stdlib.

## Run it

```bash
# default: 3 reviewer rounds, Python spec output
uv run qa_planner.py examples/login.yaml

# TypeScript spec
uv run qa_planner.py --lang typescript examples/petstore.json

# Verbose: every LLM message, every tool call, per-round verdict
uv run qa_planner.py -v --max-rounds 2 examples/login.yaml

# Smoke: planner only, no review, no codegen
uv run qa_planner.py --max-rounds 0 examples/login.yaml
```

Specs can also be freeform `.md`/`.txt` notes — `load_api_spec` returns
them as raw text and the planner skips `list_endpoints`.

## Artifacts (gitignored)

- `output/<slug>-test-plan.md` — the (latest) plan.
- `output/tests/<slug>.spec.py` or `.spec.ts` — the generated Playwright spec.

The slug comes from the planner (lowercased, non-alnum → `-`), e.g.
`login-api` or `swagger-petstore`. Spec and plan share the same slug so
they stay paired.

On revisions the plan file is **overwritten in place** — no `-v1.md`,
`-v2.md` history. Look at `git diff` if you need to compare.

## The five tools

Deterministic Python; the model decides when to call each.

| Tool | Used by | Purpose |
|---|---|---|
| `load_api_spec(path)` | planner | Read + parse YAML/JSON/freeform from disk. |
| `list_endpoints(parsed_spec)` | planner | Flatten OpenAPI `paths` into method/path/summary/codes. |
| `save_plan(slug, markdown)` | planner | Write Markdown to `output/<slug>-test-plan.md`. |
| `submit_review(approved, issues)` | reviewer | Structured verdict — drives the loop. |
| `save_spec(code)` | codegen | Write the spec file. Path is built by the orchestrator from slug + `--lang`, not chosen by the model. |

The last one is deliberate: less filesystem choice for the model = less
to get wrong.

## CLI

```
uv run qa_planner.py [-v] [--lang python|typescript]
                     [--max-rounds N] <spec_file>
```

| Flag | Default | Notes |
|---|---|---|
| `-v` / `--verbose` | off | Phase headers, every assistant message, every tool call & result. |
| `--lang` | `python` | `python` → `pytest-playwright`, `typescript` → `@playwright/test`. |
| `--max-rounds` | `3` | Reviewer ↔ planner rounds. `0` skips review and codegen entirely. |

## Config

| Env var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Required. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Any Chat Completions model with tool support. |

Shell env wins over `.env`.

Hard-coded in source: `MAX_TURNS_PER_PHASE = 10`. If a single phase makes
more than 10 tool-call round-trips, you'll see
`[warn] <phase>: hit MAX_TURNS_PER_PHASE=10` and the loop stops. Bump it
in `qa_planner.py` if you hit it on a huge spec.

## Files

```
qa_planner.py             # prompts, tools, three phase fns, orchestrator, CLI
examples/                 # sample specs
output/                   # generated plans          (gitignored)
output/tests/             # generated spec files     (gitignored)
PLAN.md                   # original design
PLAN-partial-flow.md      # next step: plan/review/codegen subcommands
```

## What this teaches

1. **Multi-role prompting** — one model, three system prompts, no fine-tuning.
2. **Structured verdicts via tool calls** — the loop reads typed args, not English.
3. **Plan → code handoff** — Phase 3 sees only the approved plan, not the spec.
   Decoupling like this is how bigger agents stay sane.
