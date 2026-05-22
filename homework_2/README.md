# my-claude-setup

My Claude Code configuration: permissions, hooks, agents, skills, and MCP servers.

## Prerequisites

- **Claude Code** installed and authenticated
- **Python 3.8+** on `PATH` — required by the `block-secrets` hook. On Windows, install from python.org (not the Microsoft Store, whose shim won't satisfy hook invocations). Verify with `python --version`.
- **Node.js + npm** — used by the MCP servers (spawned via `npx`) and the Playwright skills
- **gh** (GitHub CLI) — used by the `commit-and-pr` agent for PR creation

## Layout

```
.claude/
  settings.json              # permissions (allow/ask/deny) + hooks
  CLAUDE.md                  # project-level instructions
  hooks/
    block-secrets.py         # PreToolUse hook: refuses writes containing literal secrets
  agents/
    commit-and-pr.md         # generates branch + commit + PR with human approval
    test-designer.md         # ISTQB-based test design (paths, scenarios, cases)
    test-automation-guide.md # Playwright code review + anti-pattern catalog
  skills/
    mark-known-bug/          # wraps a failing Playwright test with test.fail() + bug annotation
    playwright-cli/          # full playwright-cli reference (with deep-dive references/)
    rotate-client-b-user/    # project-specific test-user rotation workflow
.mcp.json                    # MCP servers: context7 (docs), playwright (browser)
```

## Permissions (`.claude/settings.json`)

Three lists govern every tool call:

| List   | Behavior                                |
|--------|-----------------------------------------|
| allow  | Runs without prompting.                 |
| ask    | Prompts before running.                 |
| deny   | Blocked outright. No in-session override. |

Highlights:
- **Allowed** without prompt: read-only git (`status`, `diff`, `log`), `Read`, `Grep`, `Glob`, `npm test`, `npx playwright test`, `gh pr view/list`.
- **Asked**: anything that mutates — `Write`, `Edit`, `git add`/`commit`/`push`, `gh pr create`, `npm install`.
- **Denied**: `rm -rf`, `sudo`, `curl … | sh`, `git push --force`, `git reset --hard`, reads of `.env`, private keys, `~/.aws/credentials`, `~/.ssh/**`, and uploads to pastebin-style services.

## Hook (`.claude/hooks/block-secrets.py`)

Python script (cross-platform) wired to `PreToolUse` for `Write|Edit`. Reads the tool payload from stdin and refuses (exit 2) if the content contains:

- Common secret env-var assignments: `API_KEY=…`, `AWS_SECRET_ACCESS_KEY=…`, `OPENAI_API_KEY=…`, `STRIPE_SECRET=…`, `DATABASE_URL=…`, etc.
- AWS access key IDs (`AKIA…`)
- GitHub tokens (`ghp_…`, `github_pat_…`)
- Anthropic / OpenAI keys (`sk-ant-…`, `sk-…`)
- PEM/SSH private key blocks

On hit, the hook writes a clear stderr message naming the file and the offending pattern. To bypass legitimately, load the value from an env var or `.env`.

## Agents

| Agent | Purpose | Model |
|---|---|---|
| `commit-and-pr` | Analyse diff → generate branch name, conventional commit, PR title/body. **Always asks before executing git operations.** GitHub-first via `gh`; Azure DevOps notes included. | sonnet |
| `test-designer` | Derive test coverage from a feature or user story using ISTQB techniques (EP, BVA, decision tables, state transition, pairwise) + exploratory charters + accessibility. Output is Markdown. | sonnet |
| `test-automation-guide` | Reviews Playwright code for anti-patterns: arbitrary `waitForTimeout`, CSS selectors over `getByRole`, missing API status checks, shared state, hardcoded credentials. | sonnet |

## Skills

| Skill | Trigger | What it does |
|---|---|---|
| `mark-known-bug` | "mark this test as a known bug", "bug is raised #5938" | Replaces `test(` with `test.fail()` + structured annotation. Test passes in CI, alerts automatically when the bug is fixed (Playwright reports "expected to fail but passed"). |
| `playwright-cli` | Anything involving the `playwright-cli` tool | Full command reference + 10 deep-dive docs under `references/` (tracing, request mocking, session management, spec-driven testing, etc.). |
| `rotate-client-b-user` | "rotate test user", "Stripe purchase limit hit" | Project-specific: registers a fresh test user, queries the Portal API for the customer ID, updates the constants file. **Paths are hardcoded to a specific repo — kept as a reference for what real project skills look like.** |

## MCP servers (`.mcp.json`)

- **context7** — fetches up-to-date library docs (React, Playwright, etc.) instead of relying on training-data recall.
- **playwright** — drives a real browser for testing / scraping.

Both are stdio servers spawned via `npx`. Pin versions in production if you commit this to a team repo.

## Reusing this setup

1. Clone or copy the `.claude/` folder and `.mcp.json` into your own project.
2. Edit `.claude/settings.json` to match the commands your project actually runs (the allow list here assumes npm + playwright + gh; swap for `uv`, `pytest`, `cargo`, etc.).
3. Decide which agents and skills are general (`commit-and-pr`, `test-designer`, `test-automation-guide`, `mark-known-bug`, `playwright-cli`) vs project-specific (`rotate-client-b-user` — drop or adapt).
4. The hook needs Python 3.8+ on PATH. Confirm with `python --version` before relying on it.
