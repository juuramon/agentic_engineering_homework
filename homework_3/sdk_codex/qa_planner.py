"""QA API Test Planner v2 — SDK variant.

Same three-phase orchestration as the no_sdk sibling, written the way the
OpenAI Agents SDK is meant to be used:

  - Each phase is an Agent[Context] with a typed output_type.
  - Tool functions are tiny @function_tool wrappers; the SDK introspects
    their signatures and docstrings to build JSON schemas for the model.
  - File I/O and loop control live in the orchestrator (Python), not in
    the model. The agents return data; the orchestrator persists it.
  - Per-run state (the spec path) is passed via RunContextWrapper, not
    module globals.

The folder is called sdk_codex/ because the homework brief said "Claude or
Codex SDK." In OpenAI's 2026 stack, Codex (the coding-agent CLI) is built
on the openai-agents package, which is the supported public surface for
custom tool calling. The Codex Python SDK itself does not expose a public
API for registering Python callbacks as tools, so this variant uses the
underlying Agents SDK directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from agents import Agent, RunContextWrapper, Runner, function_tool
from pydantic import BaseModel, Field

DEFAULT_MODEL = "gpt-4o-mini"
OUTPUT_DIR = Path("output")
TESTS_DIR = OUTPUT_DIR / "tests"
MAX_TURNS_PER_PHASE = 10


# ============================================================================
# Per-run context — passed through Runner.run(context=...) and reachable
# inside tools as wrapper.context. Replaces no_sdk's module-level globals.
# ============================================================================

@dataclass
class PlannerContext:
    spec_path: str


# ============================================================================
# Typed agent outputs. output_type=<model> tells the SDK to use OpenAI
# structured outputs, so result.final_output is the parsed model instance.
# ============================================================================

class PlannedReport(BaseModel):
    slug: str = Field(description="Short kebab-case identifier derived from the API "
                                  "title, e.g. 'swagger-petstore' or 'login-api'.")
    markdown: str = Field(description="Full Markdown body of the test plan.")


class Verdict(BaseModel):
    blocking_issues: list[str] = Field(
        default_factory=list,
        description="Issues that would make the test plan wrong or incomplete "
                    "(missing endpoint, missing auth scenario, vague assertion that "
                    "can't be tested). At most 5, ranked by severity. Empty when "
                    "the plan is ready to ship.")
    suggestions: list[str] = Field(
        default_factory=list,
        description="Nice-to-have refinements that do not block shipping "
                    "(tighter assertions, additional edge cases, naming). Not used "
                    "by the orchestrator; surfaced for the human reader.")


class GeneratedSpec(BaseModel):
    code: str = Field(description="Full source of the Playwright spec file. "
                                  "No Markdown fences, no commentary.")


# ============================================================================
# Tools — only the two that the planner genuinely needs from the host.
# Everything else (file writes, verdicts) flows through typed agent outputs.
# ============================================================================

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


@function_tool
def load_api_spec(wrapper: RunContextWrapper[PlannerContext]) -> dict[str, Any]:
    """Read and parse the API spec file at the path provided by the orchestrator.

    Returns either {"format": "openapi", "raw": <dict>} for YAML/JSON specs,
    {"format": "freeform", "text": <str>} for .md/.txt notes, or {"error": ...}
    when the file is missing, unreadable, or malformed.
    """
    path = wrapper.context.spec_path
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


@function_tool(strict_mode=False)
def list_endpoints(parsed_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an OpenAPI spec into a list of {method, path, summary, response_codes}.

    Args:
        parsed_spec: The dict returned by load_api_spec for an openapi-format file.
    """
    raw = parsed_spec.get("raw", parsed_spec)
    if not isinstance(raw, dict):
        return []
    endpoints: list[dict[str, Any]] = []
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


# ============================================================================
# System prompts. Shorter than the no_sdk versions: the SDK enforces the
# output shape via output_type, so the prompts don't need to teach the
# model about a save_plan / submit_review / save_spec tool.
# ============================================================================

PLANNER_INSTRUCTIONS = """You are a senior QA engineer drafting a Markdown
test plan for an API.

You have two tools:
  - load_api_spec()        — read the spec the orchestrator pointed you at.
  - list_endpoints(spec)   — flatten the OpenAPI paths into a list.

Workflow: call load_api_spec, then (if format=openapi) list_endpoints, then
draft a plan that covers EVERY endpoint with happy-path, negative, auth,
security, and contract checks.

Return a PlannedReport with:
  - slug: a short kebab-case identifier derived from the API title,
          e.g. 'swagger-petstore' or 'login-api'. Reused for the test file.
  - markdown: the full plan body.

This agent only handles the FIRST draft. Revisions go to the amender."""


AMENDER_INSTRUCTIONS = """You are the same QA engineer revising your own
previous Markdown test plan in response to reviewer feedback.

You receive:
  1. The current plan (Markdown).
  2. A list of issues to address. The user message will say whether they
     are 'blocking' (must-fix) or 'suggestions' (polish).

Your job: return a PlannedReport whose markdown is the SAME plan with the
flagged issues addressed. Do NOT rewrite unrelated sections. Do NOT change
the slug. Do NOT add new sections beyond what the issues require.

Rules of thumb:
  - If an issue says 'missing X', add X in the appropriate existing section.
  - If an issue says 'assertion Y is vague', rewrite that one bullet, leave
    the rest alone.
  - If an issue is unclear, make the smallest plausible change and move on.
  - For suggestion batches: address as many as you reasonably can in one
    pass while preserving everything else. The loop terminates when the
    suggestion count stops dropping, so address the easy wins first.

Preserve the overall structure, the existing wording where the reviewer
didn't object, and the slug. This is a surgical patch, not a rewrite."""


REVIEWER_INSTRUCTIONS = """You are a meticulous QA lead reviewing a peer's
Markdown test plan for an API. Behave like a real PR reviewer: distinguish
"this is broken" from "this could be tighter."

Return a Verdict with two lists:

  blocking_issues — things that would make the plan WRONG or INCOMPLETE if
                    a test engineer implemented it as-is. Examples:
                      • A documented endpoint is missing entirely.
                      • A required category is missing (no auth tests for
                        an authenticated endpoint, no negative cases for
                        a validated body).
                      • An assertion is so vague it can't be implemented
                        ('check response is good').
                    Cap at 5. Rank by severity (most critical first). If
                    the plan is shippable, return [].

  suggestions    — refinements that would IMPROVE the plan but are not
                    required for correctness. Examples:
                      • Add an edge case for very long input.
                      • Tighten an existing assertion.
                      • Rename a section for clarity.
                    No cap. Not used by the loop; just surfaced for the
                    human reader.

A plan with empty blocking_issues will SHIP. Be willing to ship plans that
have suggestions but no blockers — perfect is the enemy of done."""


CODEGEN_INSTRUCTIONS_PY = """You are a senior Playwright test engineer.
Given a Markdown QA test plan, return ONE production-quality pytest-playwright
spec file as a GeneratedSpec(code=...).

═══ IMPORTS & TYPING ═══
- `from playwright.sync_api import APIRequestContext, APIResponse`
- `import pytest`, `import os`
- Type hints on every helper (parameters and return types).
- TypedDict or dataclass for every response shape:
    from typing import TypedDict
    class LoginSuccessResponse(TypedDict):
        token: str
        expires_in: int | None
- Never use bare `dict` without typed keys.

═══ CONFIGURATION ═══
- Read base URL, credentials, secrets from env vars with sensible defaults:
    VALID_EMAIL = os.environ.get("SOME_VAR", "fallback@example.com")
- Group env-driven constants at the top under `# ─── Configuration ───`.
- Use relative paths (e.g. '/api/login'); assume base_url comes from conftest.
- Name magic numbers as constants: `RESPONSE_TIME_LIMIT_MS = 3000`

═══ FIXTURES & HELPERS ═══
- Typed request helper:
    def send_login_request(request: APIRequestContext, body: dict | None,
                           headers: dict[str, str] | None = None) -> APIResponse: ...
- Typed JSON parser:
    def parse_json_body(response: APIResponse) -> dict: ...
- Named assertion helpers: assert_valid_login_response(body),
  assert_validation_error(response, label).
- Single-purpose helpers — never combine send + validate.
- Verb prefixes: send_…, parse_…, assert_…

═══ TEST STRUCTURE ═══
- Group tests by concern using classes:
    class TestHappyPath: ...
    class TestAuthentication: ...
    class TestValidationMissingFields: ...
- Descriptive snake_case names like test_returns_401_for_invalid_credentials.
- One behavior per test.

═══ PARAMETERIZATION ═══
- `@pytest.mark.parametrize` — one test per case, never loop inside a test.
- Include a human-readable label.
- Test data as module-level lists of tuples/dicts.

═══ ASSERTIONS ═══
- Specific status codes: `assert response.status == 401`
- Multi-code tolerance needs a diagnostic message:
    assert response.status in (400, 422), f"{label}: expected 400 or 422, got {response.status}"
- No vacuous assertions (`>= 0`, `< 600`, etc).
- Validate Content-Type on successes.
- Assert individual fields by name, not `expect.any`.

═══ AVOID ═══
- Duplicate tests. Metadata-only tests. Tests of framework behaviour.
- Bare `except Exception`. `# type: ignore`. `Any` annotations.

Return GeneratedSpec(code=<raw Python source>). No Markdown fences."""


CODEGEN_INSTRUCTIONS_TS = """You are a senior Playwright test engineer.
Given a Markdown QA test plan, return ONE production-quality Playwright
TypeScript spec file as a GeneratedSpec(code=...).

═══ IMPORTS & TYPES ═══
- `import { test, expect, APIRequestContext, APIResponse } from '@playwright/test'`
- A TypeScript interface for every response shape (e.g. LoginSuccessResponse).
- Never bare `unknown` with casts — parse into a typed interface.

═══ CONFIGURATION ═══
- Read base URL, credentials, secrets from env with defaults:
    const VALID_EMAIL = process.env.SOME_VAR ?? 'fallback@example.com';
- Group constants at the top under `// ─── Configuration ───`.
- Use relative paths; assume baseURL is set in playwright.config.ts.
- Name magic numbers: `const RESPONSE_TIME_LIMIT_MS = 3000;`

═══ HELPERS ═══
- Typed request helper:
    async function sendRequest(request: APIRequestContext, body: unknown,
                               headers?: Record<string, string>): Promise<APIResponse>
- Typed JSON parser:
    async function parseJsonBody<T = unknown>(response: APIResponse): Promise<T>
- Named assertion helpers: expectValidResponse(body), expectValidationError(...).
- Single-purpose; verb prefixes (send…, parse…, expect…).

═══ TEST STRUCTURE ═══
- Nested `test.describe` blocks grouped by concern.
- Descriptive titles, never numbered.
- One behavior per test.

═══ PARAMETERIZATION ═══
- Loop OUTSIDE test() to generate one test per case.
- Include a label in every parameterized test title.

═══ ASSERTIONS ═══
- Specific status codes: `expect(response.status()).toBe(401)`
- Multi-code tolerance needs a diagnostic message via expect(...).toBe(true).
- No vacuous assertions.
- Validate Content-Type on successes.
- Assert individual fields by name.

═══ AVOID ═══
- Duplicate tests. Metadata-only tests. Tests of framework behaviour.
- `!` non-null without a prior check. `as Record<string, unknown>` casts.

Return GeneratedSpec(code=<raw TypeScript source>). No Markdown fences."""


# ============================================================================
# Agents — three small declarative definitions, one per phase.
# ============================================================================

def build_planner(model: str) -> Agent[PlannerContext]:
    return Agent[PlannerContext](
        name="QA Planner",
        instructions=PLANNER_INSTRUCTIONS,
        model=model,
        tools=[load_api_spec, list_endpoints],
        output_type=PlannedReport,
    )


def build_amender(model: str) -> Agent[PlannerContext]:
    # No tools: the amender works purely from the current plan in its prompt.
    # No spec re-parsing — that already happened in the planner phase.
    return Agent[PlannerContext](
        name="QA Amender",
        instructions=AMENDER_INSTRUCTIONS,
        model=model,
        output_type=PlannedReport,
    )


def build_reviewer(model: str) -> Agent[PlannerContext]:
    return Agent[PlannerContext](
        name="QA Reviewer",
        instructions=REVIEWER_INSTRUCTIONS,
        model=model,
        output_type=Verdict,
    )


def build_codegen(model: str, lang: str) -> Agent[PlannerContext]:
    return Agent[PlannerContext](
        name=f"QA Codegen ({lang})",
        instructions=CODEGEN_INSTRUCTIONS_PY if lang == "python" else CODEGEN_INSTRUCTIONS_TS,
        model=model,
        output_type=GeneratedSpec,
    )


# ============================================================================
# Orchestrator — Python owns: file I/O, the revision loop, the final paths.
# Agents own: prose, planning, review, code.
# ============================================================================

def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-") or "api"


def _write_plan(report: PlannedReport) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{_slugify(report.slug)}-test-plan.md"
    out.write_text(report.markdown, encoding="utf-8")
    return out


def _write_spec(slug: str, lang: str, code: str) -> Path:
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = "py" if lang == "python" else "ts"
    out = TESTS_DIR / f"{_slugify(slug)}.spec.{ext}"
    out.write_text(code, encoding="utf-8")
    return out


async def orchestrate(spec_path: str, lang: str, max_rounds: int,
                      verbose: bool) -> None:
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    ctx = PlannerContext(spec_path=spec_path)
    planner = build_planner(model)
    amender = build_amender(model)
    reviewer = build_reviewer(model)
    codegen = build_codegen(model, lang)

    # ── Phase 1: initial plan ────────────────────────────────────────────
    if verbose:
        _vlog("=== Phase 1: planner ===", f"spec={spec_path} model={model}")
    result = await Runner.run(
        planner,
        f"Plan QA tests for the API spec at: {spec_path}",
        context=ctx,
        max_turns=MAX_TURNS_PER_PHASE,
    )
    report: PlannedReport = result.final_output
    plan_path = _write_plan(report)
    print(f"[plan] saved {plan_path}", file=sys.stderr)

    if max_rounds <= 0:
        print("[skip] max_rounds=0; skipping reviewer and codegen", file=sys.stderr)
        return

    # ── Phase 2: review + amend loop ─────────────────────────────────────
    # Two-mode state machine within a single shared round budget:
    #   mode=fix_blockers  → amend with blockers until blocking_issues == [].
    #                        Convergence guard: stop if blockers don't drop.
    #   mode=polish        → amend with suggestions until the count stops
    #                        strictly decreasing. Tightening that no longer
    #                        tightens is done.
    if verbose:
        _vlog("=== Phase 2: reviewer ===", f"max_rounds={max_rounds}")
    mode = "fix_blockers"
    prev_count: int | None = None
    for rnd in range(1, max_rounds + 1):
        rev_result = await Runner.run(
            reviewer,
            f"Review this Markdown test plan:\n\n{report.markdown}",
            context=ctx,
            max_turns=MAX_TURNS_PER_PHASE,
        )
        verdict: Verdict = rev_result.final_output
        n_block = len(verdict.blocking_issues)
        n_sugg = len(verdict.suggestions)
        print(f"[round {rnd} {mode}] blocking={n_block} suggestions={n_sugg}",
              file=sys.stderr)

        # State transition: blockers cleared → switch to polish mode.
        if mode == "fix_blockers" and n_block == 0:
            mode = "polish"
            prev_count = None  # reset guard for the new mode
            print("[ok] no blocking issues; entering polish mode", file=sys.stderr)
            if n_sugg == 0:
                print("[ok] no suggestions either; shipping", file=sys.stderr)
                break

        if mode == "fix_blockers":
            issues = verdict.blocking_issues
            label = "blocking"
            count = n_block
        else:
            issues = verdict.suggestions
            label = "suggestion"
            count = n_sugg
            if count == 0:
                print("[ok] no suggestions left; shipping", file=sys.stderr)
                break

        # Convergence guard: in either mode, stop if the count fails to drop.
        if prev_count is not None and count >= prev_count:
            print(f"[ok] {label} count not decreasing ({prev_count} → {count}); "
                  f"shipping", file=sys.stderr)
            break
        prev_count = count

        amend_msg = (
            "Here is the current plan to amend:\n\n"
            f"{report.markdown}\n\n"
            f"The reviewer flagged these {label} issues. Address them and "
            f"leave the rest of the plan untouched:\n"
            + "\n".join(f"- {i}" for i in issues)
        )
        amend_result = await Runner.run(amender, amend_msg, context=ctx,
                                        max_turns=MAX_TURNS_PER_PHASE)
        report = amend_result.final_output
        plan_path = _write_plan(report)
        print(f"[plan] amended ({label}) → {plan_path}", file=sys.stderr)
    else:
        print(f"[warn] hit max_rounds={max_rounds}; shipping latest revision",
              file=sys.stderr)

    # ── Phase 3: codegen ─────────────────────────────────────────────────
    if verbose:
        _vlog("=== Phase 3: codegen ===", f"lang={lang} slug={report.slug}")
    cg_result = await Runner.run(
        codegen,
        f"Generate the Playwright {lang} spec for this approved plan:\n\n{report.markdown}",
        context=ctx,
        max_turns=MAX_TURNS_PER_PHASE,
    )
    spec: GeneratedSpec = cg_result.final_output
    spec_path_out = _write_spec(report.slug, lang, spec.code)
    print(f"[spec] saved {spec_path_out}", file=sys.stderr)


# ============================================================================
# Env loader + CLI. Same shape as no_sdk for parity.
# ============================================================================

def _load_env() -> None:
    """Stdlib KEY=VALUE loader, script-relative (CWD-independent).

    Lookup order: sdk_codex/.env (per-variant), then homework_2/.env (shared
    with no_sdk). First hit wins. Shell env always wins over .env.
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


def _vlog(header: str, body: str) -> None:
    print(header, file=sys.stderr)
    print(body, file=sys.stderr)


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
            try:
                max_rounds = int(args[i])
            except (IndexError, ValueError):
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

    _load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("error: OPENAI_API_KEY not set.")

    asyncio.run(orchestrate(positional[0], lang=lang, max_rounds=max_rounds,
                            verbose=verbose))


if __name__ == "__main__":
    main()
