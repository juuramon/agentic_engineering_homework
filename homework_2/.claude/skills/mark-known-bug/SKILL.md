---
name: mark-known-bug
description: Mark a failing Playwright test as a known application bug using test.fail() with a structured annotation block. Keeps CI green, maintains coverage, and auto-alerts when the bug is resolved. Use this skill when a test fails due to a known application bug with a raised work item, or when the user asks to annotate a test with a bug reference.
---

# Mark Test as Known Bug

Apply `test.fail()` + structured `annotation` to a failing Playwright test that corresponds to a known application bug with a raised work item (Azure DevOps, GitHub Issues, Jira, etc.).

## When to use

- Test fails because of an **application bug** (not test code).
- Bug has been raised and you have a number (e.g. `#5938` or `AB#5938`).
- User says: "mark this as a known bug", "this is a known issue", "bug is raised", or gives a bug number alongside a failing test.

## Do NOT use for

- Flaky tests — fix the selector or add proper waits.
- Test code bugs — fix the test.
- Unimplemented features — use `test.fixme()` instead.

---

## Steps

### 1. Identify the test

Locate the failing test:

```bash
grep -rn "<test name fragment>" tests/
```

Note the full test title (including `describe` block).

### 2. Identify bug details

You need:
- **Bug number** — e.g. `5938`
- **Bug title** — full title as it appears in the tracker. Ask the user if not provided.

### 3. Apply the pattern

Replace `test(` with `test.fail(` and add the `annotation` block as the second argument (before the async function).

**Before:**
```typescript
test('should show validation error when email is missing', async ({ page }) => {
  // test body
});
```

**After:**
```typescript
// BUG AB#<NUMBER>: <Bug title>
// test.fail() keeps CI green and auto-alerts when the bug is resolved
// (Playwright reports "expected to fail but passed" → signal to remove test.fail())
test.fail(
  'should show validation error when email is missing',
  {
    annotation: {
      type: 'bug',
      description: 'AB#<NUMBER> — <Full bug title>'
    }
  },
  async ({ page }) => {
    // test body unchanged
  }
);
```

**The test body is never modified — only the wrapper.**

### 4. Preserve fixtures

Keep `{ page }`, `{ page, context }`, etc. exactly as they were on the async function argument.

### 5. Nested describes

If the test is inside `test.describe()`, no changes to the describe — only `test(` → `test.fail(`.

### 6. Verify

```bash
npx playwright test <file> --project=chromium --workers=1 --reporter line -g "<test name>"
```

Expected output: `1 passed` (expected failures count as passed in Playwright).

---

## After the bug is fixed

When the application bug is resolved and deployed:
1. The test will pass.
2. `test.fail()` expected failure → Playwright reports **"Expected to fail, but passed"** as a failure in CI.
3. **That's your signal:** remove `test.fail()`, restore `test(`, remove the annotation block + comment.
4. Re-run to confirm a clean pass.

---

**Source:** ported from a GitHub Copilot skill. Reference implementation in the original project: `tests/ui/client-d/voluntary_contribution.spec.ts` (search for `AB#5938`).
