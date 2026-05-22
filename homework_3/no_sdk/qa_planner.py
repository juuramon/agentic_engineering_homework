"""QA API Test Planner v2 — planner → reviewer loop → Playwright codegen.

A three-phase orchestration of a single LLM playing different roles, all via
the OpenAI Chat Completions API and the stdlib (plus PyYAML).

  Phase 1  planner   spec        → Markdown test plan
  Phase 2  reviewer  plan        → {approved, issues}; loop revises until ok
  Phase 3  codegen   plan + lang → Playwright spec file
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-5.4-mini"
OUTPUT_DIR = Path("output")
TESTS_DIR = OUTPUT_DIR / "tests"
MAX_TURNS_PER_PHASE = 10


PLANNER_PROMPT = """You are a senior QA engineer drafting a Markdown test plan
for an API.

Tools:
  1. load_api_spec(path)         — parse the spec file from disk.
  2. list_endpoints(parsed_spec) — flat list of endpoints (only for format='openapi').
  3. save_plan(slug, markdown)   — write the plan to ./output/<slug>-test-plan.md.

Workflow: load_api_spec → (list_endpoints if openapi) → draft a plan that
covers EVERY endpoint with happy path, negative, auth, security, and contract
checks → save_plan ONCE at the end.

The slug should be a short kebab-case identifier derived from the API title,
e.g. 'swagger-petstore' or 'login-api'. The same slug will be reused for the
generated test file, so pick something sensible.

If you are given reviewer issues to address, revise the plan to fix them and
save the revised version (same slug)."""


REVIEWER_PROMPT = """You are a meticulous QA lead reviewing a peer's Markdown
test plan for an API.

You receive the full Markdown plan in the user message. Read it carefully and
decide whether it is good enough to hand off to a test-automation engineer.

Look for:
  - Missing endpoints or methods.
  - Missing categories of tests (negative, auth, contract, security).
  - Vague, untestable assertions ('looks right', 'works as expected').
  - Missing test data / preconditions.

You MUST call the submit_review tool exactly once with:
  - approved: true if the plan is solid, false if it needs revision.
  - issues:  a list of concrete, actionable issues for the planner to fix.
             Empty list if approved.

Do not respond with prose — only the tool call."""


CODEGEN_PROMPT_PY = """You are a senior Playwright test engineer. Given a Markdown
QA test plan, generate ONE production-quality Playwright Python (pytest-playwright)
spec file that implements the API tests from the plan.

═══ IMPORTS & TYPING ═══
- Use `from playwright.sync_api import APIRequestContext, APIResponse`
- Use `import pytest` and `import os`
- Add type hints to ALL helper functions (parameters and return types).
- Define TypedDict or dataclass for every response shape:
    from typing import TypedDict
    class LoginSuccessResponse(TypedDict):
        token: str
        expires_in: int | None
- Never use bare `dict` without typed keys — always parse into a typed structure.

═══ CONFIGURATION ═══
- Read base URL, credentials, and secrets from environment variables with sensible defaults:
    VALID_EMAIL = os.environ.get("SOME_VAR", "fallback@example.com")
- Group ALL env-driven constants at the top of the file under a `# ─── Configuration ───` comment.
- Use relative paths for requests (e.g., '/api/login') — assume base_url is set in pytest config or conftest.
- Name magic numbers as constants: `RESPONSE_TIME_LIMIT_MS = 3000`

═══ FIXTURES & HELPERS ═══
- Create a typed request helper:
    def send_login_request(request: APIRequestContext, body: dict | None, headers: dict[str, str] | None = None) -> APIResponse:
- Create a typed JSON parser:
    def parse_json_body(response: APIResponse) -> dict:
        text = response.text()
        assert text, "response body should not be empty"
        return json.loads(text)
- Create named assertion helpers: `assert_valid_login_response(body)`, `assert_validation_error(response, label)`
- Helpers must be single-purpose — never combine "send + validate" in one helper.
- Name helpers with verb prefixes: send_…, parse_…, assert_…

═══ TEST STRUCTURE ═══
- Use classes to group tests by concern:
    class TestHappyPath:
        def test_returns_200_with_valid_token(self, request): ...

    class TestAuthentication:
        def test_returns_401_for_invalid_credentials(self, request): ...

    class TestValidationMissingFields:
        def test_rejects_missing_email(self, request): ...
- DO NOT number test names. Use descriptive snake_case: `test_returns_401_for_invalid_credentials`
- One behavior per test — never combine positive and negative cases.

═══ PARAMETERIZATION ═══
- Use `@pytest.mark.parametrize` to generate one test per case:
    @pytest.mark.parametrize("name,body", [
        ("missing_email", {"password": VALID_PASSWORD}),
        ("missing_password", {"email": VALID_EMAIL}),
        ("empty_body", {}),
    ])
    def test_rejects_request_with_missing_field(self, request, name, body): ...
- NEVER loop inside a single test function — when one iteration fails, remaining cases are skipped and the failure is unidentifiable.
- Include a human-readable label via the `name` parameter or pytest IDs.
- Define test data as module-level lists of tuples or dicts with clear variable names.

═══ ASSERTIONS ═══
- Assert SPECIFIC status codes: `assert response.status == 401`
- When multiple codes are acceptable, provide diagnostic failure messages:
    assert response.status in (400, 422), f"{label}: expected 400 or 422, got {response.status}"
- NEVER write vacuous assertions:
    BAD:  assert len(text) >= 0           ← always true
    BAD:  assert response.status >= 200   ← passes for anything
    BAD:  assert response.status < 600    ← passes for anything
- NEVER use `assert x in [200, 400]` without a failure message — it gives no diagnostic.
- Validate Content-Type header on success responses.
- For typed response bodies, assert individual fields with specific expected values or types.

═══ WHAT TO AVOID ═══
- No duplicate tests (two tests asserting the same request → same response).
- No tests that only attach metadata without verifying behavior.
- No tests that verify framework behavior ("does Playwright send headers").
- No bare `except Exception` — let assertion errors propagate.
- No `# type: ignore` comments — fix the types instead.
- No `Any` type annotations — use specific types or TypedDict.

═══ OUTPUT RULES ═══
You MUST call the save_spec tool exactly once with the full file contents in
the `code` argument. The orchestrator chooses the file path; you only supply
code. Do not include Markdown fences or commentary in `code` — just the raw
Python source."""


CODEGEN_PROMPT_TS = """You are a senior Playwright test engineer. Given a Markdown
QA test plan, generate ONE production-quality Playwright TypeScript spec file
that implements the API tests from the plan.

═══ IMPORTS & TYPES ═══
- Use `import { test, expect, APIRequestContext, APIResponse } from '@playwright/test'`
- Define a TypeScript interface for EVERY response shape (e.g., `interface LoginSuccessResponse { token: string; expires_in?: number; }`)
- Never use bare `unknown` with casts — always parse into a typed interface via a generic helper.

═══ CONFIGURATION ═══
- Read base URL, credentials, and secrets from environment variables with sensible defaults:
    const VALID_EMAIL = process.env.SOME_VAR ?? 'fallback@example.com';
- Group ALL env-driven constants at the top under a `// ─── Configuration ───` section.
- Use relative paths for requests (e.g., '/api/login') — assume baseURL is set in playwright.config.ts.
- Name magic numbers as constants: `const RESPONSE_TIME_LIMIT_MS = 3000;`

═══ HELPERS ═══
- Create a typed request helper:
    async function sendRequest(request: APIRequestContext, body: unknown, headers?: Record<string, string>): Promise<APIResponse>
- Create a typed JSON parser:
    async function parseJsonBody<T = unknown>(response: APIResponse): Promise<T>
- Create named assertion helpers: `expectValidResponse(body)`, `expectValidationError(response, label)`
- Helpers must be single-purpose — never combine "send + validate" in one helper.
- Name helpers with verb prefixes: send…, parse…, expect…

═══ TEST STRUCTURE ═══
- Use nested `test.describe` blocks grouped by concern:
    test.describe('POST /api/resource', () => {
      test.describe('Happy Path', () => { ... });
      test.describe('Authentication', () => { ... });
      test.describe('Validation - Missing Fields', () => { ... });
      test.describe('Validation - Invalid Types', () => { ... });
      ...
    });
- DO NOT number test names. Use descriptive titles: `test('returns 401 for invalid credentials', ...)`
- One behavior per test — never combine positive and negative cases.

═══ PARAMETERIZATION ═══
- When multiple inputs test the same behavior, loop OUTSIDE `test()` to generate one test per case:
    for (const { name, body } of missingFieldCases) {
      test(`rejects request with ${name}`, async ({ request }) => { ... });
    }
- NEVER loop inside a single test() — when one iteration fails, remaining cases are skipped and the failure is unidentifiable.
- Include a human-readable label in every parameterized test title.
- Define test data arrays with typed interfaces at module scope (or import from a companion file).

═══ ASSERTIONS ═══
- Assert SPECIFIC status codes: `expect(response.status()).toBe(401)`
- When multiple codes are acceptable, provide diagnostic failure messages:
    const status = response.status();
    expect(status === 400 || status === 422, `${label}: expected 400 or 422, got ${status}`).toBe(true);
- NEVER write vacuous assertions:
    BAD:  expect(text.length).toBeGreaterThanOrEqual(0)   ← always true
    BAD:  expect(status).toBeGreaterThanOrEqual(200)      ← passes for anything
    BAD:  expect(status).toBeLessThan(600)                ← passes for anything
- NEVER use `expect([...].includes(x)).toBeTruthy()` — it gives zero diagnostic on failure.
- Use `expect(value).toBeDefined()` for existence checks, not `.toBeTruthy()`.
- Validate Content-Type header on success responses.
- For typed response bodies, assert individual fields, not `expect.objectContaining` with `expect.any`.

═══ WHAT TO AVOID ═══
- No duplicate tests (two tests asserting the same request → same response).
- No tests that only attach metadata without verifying behavior.
- No tests that verify framework behavior ("does Playwright send headers").
- No `!` non-null assertions without a preceding defined/truthy check.
- No `as Record<string, unknown>` casts — use a proper interface.

═══ OUTPUT RULES ═══
You MUST call the save_spec tool exactly once with the full file contents in
the `code` argument. The orchestrator chooses the file path; you only supply
code. Do not include Markdown fences or commentary in `code` — just the raw
TypeScript source."""


# ----- tools ---------------------------------------------------------------

def load_api_spec(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"error": f"file not found: {path}"}
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            return {"format": "openapi", "raw": yaml.safe_load(text)}
        if suffix == ".json":
            return {"format": "openapi", "raw": json.loads(text)}
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        return {"error": f"parse error in {path}: {e}"}
    if suffix in (".md", ".txt"):
        return {"format": "freeform", "text": text}
    return {"error": f"unsupported file type: {suffix}"}


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def list_endpoints(parsed_spec: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if parsed_spec is None:
        parsed_spec = kwargs
    raw = parsed_spec.get("raw", parsed_spec)
    if not isinstance(raw, dict):
        return []
    endpoints = []
    for path, item in (raw.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": op.get("summary") or op.get("description") or "",
                "response_codes": sorted((op.get("responses") or {}).keys()),
            })
    return endpoints


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-") or "api"


# State captured by the planner / codegen save tools. Populated inside the
# phase functions so the orchestrator can read the artifacts back.
_PLAN_STATE: dict[str, Any] = {}
_SPEC_STATE: dict[str, Any] = {}


def save_plan(slug: str, markdown: str) -> dict[str, str]:
    safe = _slugify(slug)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{safe}-test-plan.md"
    out.write_text(markdown, encoding="utf-8")
    _PLAN_STATE["slug"] = safe
    _PLAN_STATE["markdown"] = markdown
    _PLAN_STATE["path"] = str(out.resolve())
    return {"saved_to": str(out.resolve()), "slug": safe}


def submit_review(approved: bool, issues: list[str] | None = None) -> dict[str, Any]:
    issues = issues or []
    return {"approved": bool(approved), "issues": list(issues)}


def _save_spec_factory(slug: str, lang: str):
    ext = "py" if lang == "python" else "ts"

    def save_spec(code: str) -> dict[str, str]:
        TESTS_DIR.mkdir(parents=True, exist_ok=True)
        out = TESTS_DIR / f"{slug}.spec.{ext}"
        out.write_text(code, encoding="utf-8")
        _SPEC_STATE["path"] = str(out.resolve())
        _SPEC_STATE["code"] = code
        return {"saved_to": str(out.resolve())}

    return save_spec


PLANNER_TOOLS = [
    {"type": "function", "function": {
        "name": "load_api_spec",
        "description": "Read and parse an API spec file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "list_endpoints",
        "description": "Flatten an OpenAPI spec into a list of endpoints.",
        "parameters": {"type": "object", "properties": {"parsed_spec": {"type": "object"}}, "required": ["parsed_spec"]},
    }},
    {"type": "function", "function": {
        "name": "save_plan",
        "description": "Save the Markdown test plan to ./output/<slug>-test-plan.md.",
        "parameters": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "markdown": {"type": "string"}},
            "required": ["slug", "markdown"],
        },
    }},
]

REVIEWER_TOOLS = [
    {"type": "function", "function": {
        "name": "submit_review",
        "description": "Submit the review verdict for the test plan.",
        "parameters": {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["approved", "issues"],
        },
    }},
]

CODEGEN_TOOLS = [
    {"type": "function", "function": {
        "name": "save_spec",
        "description": "Save the generated Playwright spec file. The orchestrator chooses the path.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    }},
]


# ----- shared helpers ------------------------------------------------------

def call_api(api_key: str, model: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]]) -> dict[str, Any]:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"model": model, "messages": messages, "tools": tools}).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API error {e.code}: {e.read().decode('utf-8', errors='replace')}") from e


def load_env() -> None:
    """Stdlib KEY=VALUE loader, script-relative (CWD-independent).

    Lookup order: no_sdk/.env (per-variant), then homework_2/.env (shared
    with sdk_codex). First hit wins. Shell env always wins over .env.
    """
    here = Path(__file__).resolve().parent
    candidates = [here / ".env", here.parent / ".env"]
    for p in candidates:
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


def vlog(header: str, body: str) -> None:
    print(header, file=sys.stderr)
    print(body, file=sys.stderr)


def _run_tool_loop(api_key: str, model: str, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]], impls: dict[str, Any],
                   verbose: bool, label: str) -> dict[str, Any]:
    """Generic tool-use loop. Returns the final assistant message dict."""
    for turn in range(1, MAX_TURNS_PER_PHASE + 1):
        resp = call_api(api_key, model, messages, tools)
        msg = resp["choices"][0]["message"]
        if verbose:
            vlog(f"--- {label} turn {turn}: assistant ---", json.dumps(msg, indent=2)[:2000])
        tool_calls = msg.get("tool_calls") or []
        entry: dict[str, Any] = {"role": "assistant", "content": msg.get("content")}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        messages.append(entry)
        if not tool_calls:
            return msg
        for call in tool_calls:
            name = call["function"]["name"]
            if verbose:
                vlog(f"--- {label} tool call: {name} ---", (call["function"].get("arguments") or "")[:500])
            else:
                print(f"[{label}] tool: {name}", file=sys.stderr)
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                impl = impls.get(name)
                if impl is None:
                    result = {"error": f"unknown tool: {name}"}
                else:
                    result = impl(**args)
            except Exception as e:
                result = {"error": f"{name} failed: {type(e).__name__}: {e}"}
            result_json = json.dumps(result, default=str)
            if verbose:
                vlog(f"--- {label} tool result: {name} ---", result_json[:2000])
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result_json})
    print(f"[warn] {label}: hit MAX_TURNS_PER_PHASE={MAX_TURNS_PER_PHASE}", file=sys.stderr)
    return {}


# ----- phases --------------------------------------------------------------

def run_planner(api_key: str, model: str, spec_path: str, verbose: bool,
                prior_issues: list[str] | None = None) -> tuple[str, str]:
    """Phase 1 (and Phase 2 revision steps). Returns (slug, markdown)."""
    _PLAN_STATE.clear()
    if prior_issues:
        user = (
            f"You previously drafted a plan for the API spec at: {spec_path}\n"
            f"The reviewer asked you to address these issues:\n"
            + "\n".join(f"- {i}" for i in prior_issues)
            + "\nRevise the plan and call save_plan with the updated Markdown (same slug)."
        )
    else:
        user = f"Plan QA tests for the API spec at: {spec_path}"
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": user},
    ]
    impls = {"load_api_spec": load_api_spec, "list_endpoints": list_endpoints, "save_plan": save_plan}
    _run_tool_loop(api_key, model, messages, PLANNER_TOOLS, impls, verbose, "planner")
    if "markdown" not in _PLAN_STATE:
        sys.exit("error: planner did not call save_plan")
    return _PLAN_STATE["slug"], _PLAN_STATE["markdown"]


def run_reviewer(api_key: str, model: str, markdown_plan: str, verbose: bool,
                 round_num: int) -> dict[str, Any]:
    """Phase 2 (one round). Returns {approved, issues}."""
    messages = [
        {"role": "system", "content": REVIEWER_PROMPT},
        {"role": "user", "content": f"Review this Markdown test plan:\n\n{markdown_plan}"},
    ]
    impls = {"submit_review": submit_review}
    # We only need one assistant turn that calls submit_review. The generic loop
    # handles that — after the tool result is appended, the model will normally
    # stop with no further tool calls and we exit.
    verdict = {"approved": False, "issues": ["reviewer did not return a verdict"]}
    for turn in range(1, MAX_TURNS_PER_PHASE + 1):
        resp = call_api(api_key, model, messages, REVIEWER_TOOLS)
        msg = resp["choices"][0]["message"]
        if verbose:
            vlog(f"--- reviewer round {round_num} turn {turn}: assistant ---",
                 json.dumps(msg, indent=2)[:2000])
        tool_calls = msg.get("tool_calls") or []
        entry: dict[str, Any] = {"role": "assistant", "content": msg.get("content")}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        messages.append(entry)
        if not tool_calls:
            break
        got_verdict = False
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "submit_review":
                try:
                    verdict = submit_review(**args)
                    result = verdict
                    got_verdict = True
                except TypeError as e:
                    result = {"error": f"submit_review failed: {e}"}
            else:
                result = {"error": f"unknown tool {name}"}
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, default=str)})
        if got_verdict:
            break
    print(f"[round {round_num}] approved={verdict['approved']} issues={len(verdict['issues'])}",
          file=sys.stderr)
    return verdict


def run_codegen(api_key: str, model: str, markdown_plan: str, slug: str,
                lang: str, verbose: bool) -> str:
    """Phase 3. Returns the saved spec path."""
    _SPEC_STATE.clear()
    prompt = CODEGEN_PROMPT_PY if lang == "python" else CODEGEN_PROMPT_TS
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": (
            f"Generate the Playwright {lang} spec for this approved test plan. "
            f"Call save_spec exactly once with the full code.\n\n{markdown_plan}"
        )},
    ]
    impls = {"save_spec": _save_spec_factory(slug, lang)}
    _run_tool_loop(api_key, model, messages, CODEGEN_TOOLS, impls, verbose, "codegen")
    if "path" not in _SPEC_STATE:
        sys.exit("error: codegen did not call save_spec")
    return _SPEC_STATE["path"]


# ----- orchestrator + CLI --------------------------------------------------

def run(spec_path: str, lang: str = "python", max_rounds: int = 3,
        verbose: bool = False) -> None:
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("error: OPENAI_API_KEY not set.")
    model = os.environ.get("OPENAI_MODEL", MODEL)

    if verbose:
        vlog("=== Phase 1: planner ===", f"spec={spec_path} model={model}")
    slug, plan = run_planner(api_key, model, spec_path, verbose)
    print(f"[plan] saved {_PLAN_STATE['path']}", file=sys.stderr)

    if max_rounds <= 0:
        print("[skip] max_rounds=0; skipping reviewer and codegen", file=sys.stderr)
        return

    if verbose:
        vlog("=== Phase 2: reviewer ===", f"max_rounds={max_rounds}")
    approved = False
    for rnd in range(1, max_rounds + 1):
        verdict = run_reviewer(api_key, model, plan, verbose, rnd)
        if verdict["approved"]:
            approved = True
            break
        slug, plan = run_planner(api_key, model, spec_path, verbose,
                                 prior_issues=verdict["issues"])
        print(f"[plan] revised → {_PLAN_STATE['path']}", file=sys.stderr)
    if not approved:
        print(f"[warn] plan not approved after {max_rounds} rounds; proceeding to codegen anyway",
              file=sys.stderr)

    if verbose:
        vlog("=== Phase 3: codegen ===", f"lang={lang} slug={slug}")
    path = run_codegen(api_key, model, plan, slug, lang, verbose)
    print(f"[spec] saved {path}", file=sys.stderr)


def main() -> None:
    args = sys.argv[1:]
    verbose = False
    lang = "python"
    max_rounds = 3
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-v", "--verbose"):
            verbose = True
        elif a == "--lang":
            i += 1
            if i >= len(args) or args[i] not in ("python", "typescript"):
                sys.exit("error: --lang must be 'python' or 'typescript'")
            lang = args[i]
        elif a.startswith("--lang="):
            v = a.split("=", 1)[1]
            if v not in ("python", "typescript"):
                sys.exit("error: --lang must be 'python' or 'typescript'")
            lang = v
        elif a == "--max-rounds":
            i += 1
            if i >= len(args):
                sys.exit("error: --max-rounds requires an integer")
            try:
                max_rounds = int(args[i])
            except ValueError:
                sys.exit("error: --max-rounds requires an integer")
        elif a.startswith("--max-rounds="):
            try:
                max_rounds = int(a.split("=", 1)[1])
            except ValueError:
                sys.exit("error: --max-rounds requires an integer")
        else:
            positional.append(a)
        i += 1
    if len(positional) != 1:
        sys.exit("usage: python qa_planner.py [-v] [--lang python|typescript] "
                 "[--max-rounds N] <spec_file>")
    run(positional[0], lang=lang, max_rounds=max_rounds, verbose=verbose)


if __name__ == "__main__":
    main()
