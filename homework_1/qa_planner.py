"""QA API Test Planner — turn an API spec into a Markdown QA test plan via tool calling.

Manual tool-use loop against OpenAI Chat Completions, stdlib only (plus PyYAML).
The LLM does the QA reasoning; tools do deterministic parsing and file I/O.
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
MAX_TURNS = 10

SYSTEM_PROMPT = """You are a senior QA engineer. Given an API spec, produce ONE
Markdown test plan covering EVERY endpoint.

Tools:
  1. load_api_spec(path)      — parse the spec file.
  2. list_endpoints(parsed_spec) — flat list of endpoints (only for format='openapi').
  3. save_report(slug, markdown) — write the report to ./output/.

Workflow: load_api_spec → (list_endpoints if openapi) → write the report covering
every endpoint with happy path, negative, auth, security, contract checks → save_report
ONCE at the end."""


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


def save_report(slug: str, markdown: str) -> dict[str, str]:
    safe = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "report"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{safe}-test-plan.md"
    out.write_text(markdown, encoding="utf-8")
    return {"saved_to": str(out.resolve())}


TOOL_IMPLS = {"load_api_spec": load_api_spec, "list_endpoints": list_endpoints, "save_report": save_report}

TOOLS = [
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
        "name": "save_report",
        "description": "Save the Markdown test plan to ./output/<slug>-test-plan.md.",
        "parameters": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "markdown": {"type": "string"}},
            "required": ["slug", "markdown"],
        },
    }},
]


def call_api(api_key: str, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"model": model, "messages": messages, "tools": TOOLS}).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI API error {e.code}: {e.read().decode('utf-8', errors='replace')}") from e


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vlog(header: str, body: str) -> None:
    print(header, file=sys.stderr)
    print(body, file=sys.stderr)


def run(spec_path: str, verbose: bool = False) -> None:
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("error: OPENAI_API_KEY not set.")
    model = os.environ.get("OPENAI_MODEL", MODEL)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Plan QA tests for the API spec at: {spec_path}"},
    ]

    for turn in range(1, MAX_TURNS + 1):
        resp = call_api(api_key, model, messages)
        msg = resp["choices"][0]["message"]
        if verbose:
            vlog(f"--- turn {turn}: assistant ---", json.dumps(msg, indent=2))
        tool_calls = msg.get("tool_calls") or []
        entry: dict[str, Any] = {"role": "assistant", "content": msg.get("content")}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        messages.append(entry)
        if msg.get("content"):
            print(msg["content"])
        if not tool_calls:
            return
        for call in tool_calls:
            name = call["function"]["name"]
            if verbose:
                vlog(f"--- tool call: {name} ---", (call["function"].get("arguments") or "")[:500])
            else:
                print(f"[tool] {name}", file=sys.stderr)
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                impl = TOOL_IMPLS.get(name)
                if impl is None:
                    result = {"error": f"unknown tool: {name}"}
                else:
                    result = impl(**args)
            except Exception as e:
                result = {"error": f"{name} failed: {type(e).__name__}: {e}"}
            result_json = json.dumps(result, default=str)
            if verbose:
                vlog(f"--- tool result: {name} ---", result_json[:2000])
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result_json})
    print(f"[warn] hit MAX_TURNS={MAX_TURNS} without natural stop", file=sys.stderr)


def main() -> None:
    args = sys.argv[1:]
    verbose = False
    positional = []
    for a in args:
        if a in ("-v", "--verbose"):
            verbose = True
        else:
            positional.append(a)
    if len(positional) != 1:
        sys.exit("usage: python qa_planner.py [-v] <spec_file>")
    run(positional[0], verbose=verbose)


if __name__ == "__main__":
    main()
