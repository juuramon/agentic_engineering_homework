# Login API Test Plan

## Scope

This plan covers the single OpenAPI operation defined in `examples/login.yaml`:

- `POST /api/login`

I verified the spec contains no other paths or methods, so endpoint coverage is complete for this file. This plan intentionally does **not** add tests for any non-existent endpoints.

## API Summary

- Purpose: authenticate a user and return a session token
- Request content type: `application/json`
- Documented responses: `200`, `401`, `422`

## Test Data and Preconditions

### Core fixture setup

Create these test accounts and fixtures before executing the suite:

1. **Valid active user**
   - Email: `active.user@example.com`
   - Password: a known valid password meeting policy, e.g. `ValidPassw0rd!`
   - State: **active**, **verified**, **not locked**
   - Expected to authenticate successfully

2. **Wrong-password user fixture**
   - Same active user account as above
   - Use an incorrect password value for negative tests

3. **Unknown user fixture**
   - Email: `unknown.user@example.com`
   - No account record exists for this email
   - Used to verify invalid credential handling without account enumeration

4. **Locked user fixture**
   - Email: `locked.user@example.com`
   - Password: known valid password
   - State: **locked** before test execution
   - Used to verify locked-account behavior

5. **Unverified user fixture**
   - Email: `unverified.user@example.com`
   - Password: known valid password
   - State: **not verified** before test execution
   - Used to verify account-state handling if the implementation distinguishes it

6. **Rate-limit / lockout test fixture state reset**
   - Ability to reset login attempt counters between tests
   - Ability to unlock or recreate the locked user fixture
   - Ability to clear any authentication/session state created by successful logins

### Environment assumptions

- Tests run against a TLS-enabled environment.
- Test harness can inspect response headers and body.
- Test harness can query or verify account state and, where applicable, login-attempt counters or lockout state.
- If the service does not support separate unverified/locked states, those tests should assert the documented fallback behavior and be recorded as not applicable only after confirmation.

## Endpoint Coverage Matrix

| Endpoint | Happy Path | Negative Input | Auth / Authorization | Security | Contract |
|---|---:|---:|---:|---:|---:|
| `POST /api/login` | Yes | Yes | Yes | Yes | Yes |
| Unsupported methods on `/api/login` (`GET`, `PUT`, `DELETE`, etc.) | N/A | Yes | Yes | Yes | Yes |

## Test Cases

### 1. Happy Path Authentication

**TC-01: Successful login with valid active user**
- Send `POST /api/login` with valid JSON:
  ```json
  {
    "email": "active.user@example.com",
    "password": "ValidPassw0rd!"
  }
  ```
- Expected status: `200`
- Expected headers:
  - `Content-Type: application/json; charset=utf-8` (or exact charset used by the service if documented; must be a JSON media type with explicit charset if the API standard requires one)
- Expected body:
  - Valid JSON object
  - Contains `token` as a non-empty string
  - Contains `expires_in` as an integer if returned by the implementation
  - No sensitive fields such as password, password hash, or internal account flags
- Assertions:
  - Token is usable only if downstream token validation is in scope; otherwise verify only format/non-empty and presence
  - Response schema matches the documented contract with no unexpected fields

### 2. Credential and Account-State Negative Cases

**TC-02: Invalid password for existing active user**
- Send valid JSON with known email and wrong password
- Expected status: `401`
- Expected outcome:
  - Authentication fails without revealing whether the email exists
  - Error body does not disclose password policy details, account state, or internal identifiers

**TC-03: Unknown user**
- Send valid JSON with `unknown.user@example.com` and any password
- Expected status: `401`
- Expected outcome:
  - Same observable behavior as invalid password, to avoid user enumeration
  - Error content and timing should not meaningfully distinguish unknown user from wrong password within normal test tolerance

**TC-04: Locked user**
- Send valid JSON for the locked account
- Expected status: `401` or a documented account-state-specific rejection status if the implementation defines one
- Expected outcome:
  - Authentication fails
  - Error response does not expose lock reason beyond a generic message
  - Account remains locked after the request

**TC-05: Unverified user**
- Send valid JSON for the unverified account
- Expected status: `401` or a documented account-state-specific rejection status if the implementation defines one
- Expected outcome:
  - Authentication fails
  - Error response does not expose verification workflow details unless explicitly documented

### 3. Request Content-Type and Payload Validation

**TC-06: Missing `Content-Type` header**
- Send request body as JSON but omit `Content-Type`
- Expected status: `415 Unsupported Media Type` if strict media-type enforcement is implemented; otherwise `422` only if the API explicitly treats it as validation failure
- Expected outcome:
  - Request is rejected
  - No login attempt is processed
  - Response is JSON error payload, not HTML or plaintext

**TC-07: Wrong media type**
- Send the same payload with `Content-Type: text/plain` or `application/x-www-form-urlencoded`
- Expected status: `415 Unsupported Media Type`
- Expected outcome:
  - Request rejected before authentication logic runs
  - Error response is sanitized and does not echo the raw payload

**TC-08: Invalid JSON syntax**
- Send malformed JSON, e.g. `{"email": "a@example.com", "password":` 
- Expected status: `400 Bad Request` or `422` if the implementation maps JSON parse failures to validation errors
- Expected outcome:
  - Parse failure is reported
  - Error body does not include parser stack traces or internal exception names

**TC-09: Wrong top-level type: array**
- Send `[]` as the JSON body
- Expected status: `422`
- Expected outcome:
  - Rejected because the schema requires an object
  - No authentication attempt occurs

**TC-10: Wrong top-level type: string**
- Send a JSON string, e.g. `"hello"`
- Expected status: `422`
- Expected outcome:
  - Rejected because the schema requires an object

**TC-11: Wrong top-level type: null**
- Send `null`
- Expected status: `422`
- Expected outcome:
  - Rejected because the schema requires an object

**TC-12: Missing required field(s)**
- Omit `email`, omit `password`, and omit both in separate subtests
- Expected status: `422`
- Expected outcome:
  - Validation error identifies missing required fields without exposing implementation internals

**TC-13: Invalid field format**
- Use malformed email values and passwords shorter than 8 characters
- Expected status: `422`
- Expected outcome:
  - Schema validation error
  - Errors reference the field name, not internal validator names

**TC-14: Extra/unknown fields**
- Add fields such as `role`, `isAdmin`, or `token` to the request body
- Expected status: `422` if unknown properties are rejected; otherwise `200/401` only if the implementation explicitly ignores them
- Expected outcome:
  - Prefer strict rejection if the API contract is intended to be closed
  - In all cases, confirm extra fields do not change authentication outcome or privilege level

**TC-15: Oversized payload**
- Send an oversized JSON body, including an excessively long email/password or many extra fields
- Expected status: `413 Payload Too Large` if a size limit is enforced; otherwise a documented `422`/`400` rejection
- Expected outcome:
  - Request does not succeed
  - Service remains responsive and does not leak memory/stack traces

### 4. Authentication / Authorization Behavior

**TC-16: No auth header required**
- Send a valid login request without `Authorization` or any other auth header
- Expected status: `200` for valid credentials
- Expected outcome:
  - Endpoint is intentionally unauthenticated for login
  - Absence of auth headers does not block access

**TC-17: Auth header does not alter behavior**
- Repeat the valid login request with an arbitrary bearer token or basic auth header attached
- Expected status: same as TC-01 for valid credentials, or same failure result for invalid credentials
- Expected outcome:
  - Supplied auth header is ignored or rejected only if the API explicitly documents that behavior
  - Presence of auth header must not elevate privileges or bypass normal credential checks

### 5. Unsupported HTTP Methods

**TC-18: Unsupported methods on `/api/login`**
- Send `GET`, `PUT`, `PATCH`, `DELETE`, and `OPTIONS`/`HEAD` if not explicitly supported
- Expected status: `405 Method Not Allowed` for unsafe unsupported methods; `OPTIONS` may return `204`/`200` only if CORS or server framework requires it
- Expected outcome:
  - Response includes an `Allow` header listing supported methods when `405` is returned
  - Method is not processed as login
  - Error response is sanitized and JSON-formatted if the service returns a body

### 6. Security Checks

**TC-19: Rate limiting / brute-force protection**
- Repeatedly submit invalid passwords for the same account and/or same IP
- Use a deterministic threshold from implementation config if available; otherwise assert a measurable lockout or throttling occurs after a small, documented number of failures (for example, 5 attempts)
- Expected outcome:
  - After threshold is reached, subsequent attempts return `429 Too Many Requests`, `401` with an enforced cooldown, or account lockout as documented
  - The same threshold is applied consistently in repeated runs
  - Successful login should not bypass a lockout triggered for the same identity during the lockout window

**TC-20: Account lockout threshold enforcement**
- Continue failed attempts until the lockout condition is triggered
- Assertions:
  - Lockout occurs at the documented threshold
  - Locked state persists for the documented duration or until manual reset
  - A successful password entered during the lockout window does not authenticate if the policy forbids it

**TC-21: Injection payload rejection**
- Submit SQL/NoSQL injection strings in `email` and `password`, such as:
  - `"' OR '1'='1"`
  - `{"$ne": null}` as a string value
  - `<script>alert(1)</script>`
- Expected outcome:
  - Requests fail with `401` or `422`, not `200`
  - No reflected script execution in responses
  - No indication of query structure, backend database, or stack traces

**TC-22: Error-response sanitization**
- Trigger each negative case above and inspect error bodies and headers
- Assertions:
  - No secrets or credentials are echoed back
  - No stack traces, framework names, SQL fragments, or file paths
  - Error messages are generic and consistent across invalid-credential cases where feasible

### 7. Response Contract Checks

**TC-23: Success response schema**
- For `200`, verify:
  - Response body is a JSON object
  - Required field: `token`
  - Optional field: `expires_in` if returned
  - No additional properties if the contract is strict; if additional properties are allowed by the implementation, record them explicitly and ensure they are non-sensitive
- Assertions:
  - `token` is a string and non-empty
  - `expires_in`, if present, is an integer greater than zero
  - `Content-Type` is `application/json` with explicit UTF-8 charset, or the environment’s documented JSON charset

**TC-24: Error response schema**
- For `401`, `415`, `422`, `400`, `405`, and `413` if used, verify:
  - Response body is JSON
  - Error schema is consistent across failures
  - The body contains a stable machine-readable error indicator if provided by the implementation
  - Additional properties are rejected if the error schema is strict; otherwise they must not expose sensitive data
- Assertions:
  - `Content-Type` is `application/json; charset=utf-8` or documented equivalent
  - No HTML error pages or plaintext stack traces

### 8. Non-Functional Checks

Only include the following if they are testable in the target environment; otherwise omit them from the execution plan.

**TC-25: TLS requirement**
- Verify login is accessible only over HTTPS/TLS
- Assertions:
  - HTTP either redirects to HTTPS or is rejected
  - TLS handshake uses an accepted protocol/cipher policy per environment standards

**TC-26: Log redaction**
- Trigger a failed login and inspect application/security logs
- Assertions:
  - Passwords are not logged
  - Tokens are not logged in plaintext
  - Sensitive request bodies are redacted or omitted

**TC-27: Token lifetime validation**
- After a successful login, verify the returned token’s expiration matches `expires_in` if provided
- Assertions:
  - Token is invalid after expiration
  - Token remains valid before expiration
  - If downstream token use is out of scope, limit the check to the response payload and documented lifetime claim

## Pass / Fail Criteria

A test passes only if:

- The observed status code matches the expected result for the scenario
- The response content type is JSON where required
- The response body matches the expected schema and does not contain sensitive data
- Security-related behavior is measurable and consistent, including lockout/rate limiting and injection resistance
- Unsupported methods return method-not-allowed behavior without executing login logic

A test fails if:

- Any unexpected endpoint exists in the spec or is discovered during execution
- Authentication succeeds for invalid, locked, or unverified accounts when it should not
- Missing/wrong media type, malformed JSON, wrong top-level type, or oversized payloads are accepted unexpectedly
- Extra fields alter the auth outcome or privilege level
- Error messages leak internals, credentials, or account-enumeration signals
- Response schemas or headers deviate from the contract without documented justification
