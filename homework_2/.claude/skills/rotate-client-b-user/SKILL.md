---
name: rotate-client-b-user
description: >
  Rotate an Client B test user that has exceeded Stripe's purchase limit.
  Registers a new user on the Client B test environment, retrieves the YourApp
  customer ID via Portal API, and updates the constants file. Use this skill
  when an Client B test is failing because a user hit Stripe purchase limits, or
  when the user asks to create a new Client B test user or rotate test data.
argument-hint: "[TEST_USER_INM_1 through TEST_USER_INM_6] - which constant to replace"
---

> **Showcase note:** Ported from a GitHub Copilot skill. The original lived under `.github/skills/rotate-client-b-user/`; in this Claude port it lives under `.claude/skills/rotate-client-b-user/`. The skill is **project-specific** — paths like `tests/others/client-b-register-user.spec.ts` and `implementation/pages/Client B/consts.ts` only exist in the original project. Kept here as a reference for what a real-world skill looks like.

# Rotate Client B Test User

Replace an Client B test user that has exceeded Stripe's purchase limit with a freshly registered one.

## Key files

- **Registration script:** [client-b-register-user.spec.ts](../../tests/others/client-b-register-user.spec.ts) — bump `userNumber` to the next available number
- **User constants:** [consts.ts](../../implementation/pages/Client B/consts.ts) — contains `TEST_USER_INM_1` through `TEST_USER_INM_6`
- **Portal API config:** [PortalConfig.ts](../../implementation/config/PortalConfig.ts) — API credentials
- **API query script:** [lookup-client-b-user.js](./lookup-client-b-user.js) — retrieves YourApp customer ID for a given user number

## Steps

### 1. Determine the next user number

Read `tests/others/client-b-register-user.spec.ts` and find the current `userNumber` value. Increment it by 1.

### 2. Update the registration script

Change `const userNumber = '<current>';` to the new number in `tests/others/client-b-register-user.spec.ts`.

### 3. Run the registration test (headed)

```bash
npx playwright test tests/others/client-b-register-user.spec.ts --project=chromium --workers=1 --reporter=line --headed
```

Run with `--headed` so the user can watch and intervene if the Client B site has changed its registration flow. The test:
1. Registers the user on Client B (Gigya)
2. Opens Mailinator to verify the email
3. Completes the user profile

**Known issue:** The test may fail on the final assertion (verifying the logged-in user name after redirect). This is flaky — the user is still created successfully. Check screenshots to confirm.

### 4. Retrieve the YourApp customer ID

Run the [lookup script](./lookup-client-b-user.js) with the new user number:

```bash
node .claude/skills/rotate-client-b-user/lookup-client-b-user.js <NEW_USER_NUMBER>
```

This authenticates against the Portal API and returns the customer ID, name, and email.

**Important:** The API uses the header `client-id` (not `x-client-id`). See `implementation/api/portalApi.ts` `createHeaders()` function for the full header set.

### 5. Update the user constant

In `implementation/pages/Client B/consts.ts`, update the target `TEST_USER_INM_*` constant with:
- `email`: `test_inm_<NUMBER>@mailinator.com`
- `name`: `Test Client B<NUMBER>`
- `id`: the customer ID from step 4
- `rotated`: today's date in `YYYY-MM-DD` format

### 6. Verify (optional)

If the user wants confirmation, run the actual Client B subscription test that was failing:

```bash
npx playwright test tests/ui/client-b.spec.ts -g "Card Payment" --project=chromium --workers=1 --reporter=line --headed
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Registration fails at email verification | Mailinator may be slow. Check inbox manually at `https://www.mailinator.com/v4/public/inboxes.jsp?to=test_inm_<NUMBER>` |
| Portal API returns 403 | Use `client-id` header, not `x-client-id` |
| Portal API returns empty customers array | User hasn't interacted with YourApp yet — customer record is created on first paywall interaction. Run a subscription test first, then query again |
| Registration test fails but user was created | Check screenshots — if Mailinator verification email arrived, the user exists. The final assertion is flaky due to redirect timing |
