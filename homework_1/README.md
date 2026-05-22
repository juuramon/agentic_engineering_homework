# QA API Test Planner

A small CLI I wrote to take the boring part out of writing a QA test plan for
an API. You point it at an OpenAPI/Swagger spec (or a freeform `.md` note),
and it asks an LLM to draft a Markdown test plan covering every endpoint —
happy paths, negative cases, auth, security, contract checks.

The interesting part for me was the **tool-calling loop**: the model doesn't
parse the spec itself, it asks the script to do it. Three small Python
functions are exposed as tools; the model decides when to call them.

## What you need

- Python 3.10+
- OpenAI API key
- `uv` (or plain `pip` if you prefer)

## Setup

```bash
cp .env.example .env       # then paste your OPENAI_API_KEY=sk-...
uv venv
uv pip install -r requirements.txt
```

Only one third-party dependency: `PyYAML`. Everything else (HTTP, JSON, env
loading) is stdlib on purpose.

## Run it

```bash
uv run qa_planner.py examples/login.yaml
uv run qa_planner.py -v examples/petstore.json   # -v prints every API call and tool I/O
```

The finished plan lands in `output/<slug>-test-plan.md`. The slug comes
from the API title, e.g. `swagger-petstore-test-plan.md`.

## The three tools

The model can call these — that's the whole interface between the LLM and
the local machine. Nothing else is exposed.

- **`load_api_spec(path)`** — reads the file off disk and parses it. YAML
  and JSON come back as a Python dict (`format: "openapi"`); `.md`/`.txt`
  come back as raw text (`format: "freeform"`).
- **`list_endpoints(parsed_spec)`** — walks `paths` in an OpenAPI doc and
  returns a flat list: method, path, summary, response codes. Saves the
  model from re-parsing the whole spec when it just wants the endpoint list.
- **`save_report(slug, markdown)`** — writes the final Markdown to
  `output/`. Called exactly once at the end of the run.

The split is deliberate: deterministic stuff (file I/O, parsing) is Python;
judgement stuff (what's worth testing, what the negative cases are) is the
model.

## Config

| Env var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Required. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Any Chat Completions model with tool support. |

Shell env wins over `.env`. The `.env` loader is a tiny stdlib helper inside
`qa_planner.py` — no `python-dotenv` dependency.

## Files

```
qa_planner.py        # the whole thing, ~190 lines
examples/            # sample specs to try
output/              # generated reports
```
