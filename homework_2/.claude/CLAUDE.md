# Project conventions

## Workflow rules
- Do not commit or push unless explicitly asked.
- Prefer `Edit` over `Write` for existing files.
- When a skill exists for the task at hand, invoke it instead of improvising.

## Tooling
- Python scripts: `uv run` (never `pip` directly).
- JS/TS: `npm` for the package manager, `npx playwright` for browser automation.
- Hooks are Python (`.claude/hooks/*.py`) so they work on Windows and Linux without separate variants.

## Sensitive data
- Never write literal secrets (API keys, tokens, private keys) into source files. The PreToolUse hook blocks this — if you hit it, load the value from an env var or `.env`.
- `.env`, `*.pem`, `id_rsa`, `credentials.json`, `~/.aws/credentials`, `~/.ssh/**` are denied by `settings.json` even for reads.
