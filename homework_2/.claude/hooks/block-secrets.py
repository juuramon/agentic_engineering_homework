#!/usr/bin/env python3
"""PreToolUse hook for Write|Edit.

Reads tool input JSON from stdin and blocks writes that contain literal secret
values. Exit 0 = allow, exit 2 = block with message on stderr.

Cross-platform (Python 3.8+, no dependencies). Wired up in .claude/settings.json.
"""

from __future__ import annotations

import json
import re
import sys

SECRET_PATTERNS = [
    # KEY = "non-trivial value"  — catches API_KEY, SECRET_KEY, PRIVATE_KEY, etc.
    re.compile(
        r'\b(API_KEY|SECRET_KEY|PRIVATE_KEY|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|'
        r'GITHUB_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|DATABASE_URL|STRIPE_SECRET)\b'
        r'\s*[:=]\s*["\']?[A-Za-z0-9_\-./+=]{12,}',
        re.IGNORECASE,
    ),
    # AWS access key ID
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    # GitHub fine-grained / classic tokens
    re.compile(r'\bghp_[A-Za-z0-9]{36,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{50,}\b'),
    # Anthropic
    re.compile(r'\bsk-ant-[A-Za-z0-9\-_]{20,}\b'),
    # OpenAI
    re.compile(r'\bsk-[A-Za-z0-9]{40,}\b'),
    # Generic private key block
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----'),
]


def extract_content(tool_input: dict) -> str:
    """Pull out the text payload from Write/Edit tool input."""
    parts: list[str] = []
    for key in ("content", "new_string", "file_text"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Don't block on parse failure — fail open, log on stderr
        print("block-secrets: could not parse hook input as JSON", file=sys.stderr)
        return 0

    tool_input = payload.get("tool_input") or {}
    content = extract_content(tool_input)
    if not content:
        return 0

    for pattern in SECRET_PATTERNS:
        match = pattern.search(content)
        if match:
            file_path = tool_input.get("file_path", "<unknown>")
            print(
                f"block-secrets: refusing to write a literal secret to {file_path}\n"
                f"  matched pattern: {pattern.pattern[:60]}...\n"
                f"  matched text:    {match.group(0)[:60]}...\n"
                f"  fix: load the value from an env var or a gitignored .env file",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
