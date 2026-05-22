# Login API Test Plan

## Scope
Validate the single endpoint in this API:
- `POST /api/login` — authenticate a user and return a session token

## Endpoint Coverage

### 1) `POST /api/login`
**Happy path**
- Submit valid JSON with a properly formatted `email` and a password meeting minimum length.
- Expect `200 OK`.
- Verify response body contains `token` as a string.
- Verify `expires_in` is present when returned and is an integer.
- Confirm the token can be used successfully on a downstream authenticated endpoint, if one is available in scope.

**Negative cases**
- Invalid email format.
- Whitespace-only `email` values (treat as missing or invalid per API behavior).
- Password shorter than 8 characters.
- Whitespace-only `password` values (treat as missing or invalid per API behavior).
- Missing `email`.
- Missing `password`.
- Empty request body.
- Malformed JSON.
- Non-JSON body sent with `Content-Type: application/json`.
- Wrong `Content-Type` (e.g. `text/plain`).
- Incorrect password with a valid email.
- Unknown email.
- Extra unexpected fields in payload (confirm accepted/ignored/rejected behavior).

**Auth checks**
- Confirm login is accessible without a prior session/token.
- Confirm authenticated requests do not break login behavior.
- Verify invalid credentials return `401 Unauthorized`.
- Validate error responses do not leak whether the email or password was incorrect.

**Security checks**
- Attempt SQL injection-style payloads in `email` and `password`.
- Attempt script/HTML injection in both fields.
- Check response bodies and logs for sensitive data exposure.
- Verify password is never echoed back in response.
- Confirm token generation is unpredictable and unique per successful login.
- Check rate limiting / brute-force protection if implemented.

**Contract checks**
- `200` response matches schema: `token` required, `expires_in` integer if present.
- `401` returns the documented status for invalid credentials (including incorrect password and unknown email) with no schema violations.
- `422` returns the documented validation error status for missing, malformed, or whitespace-only fields.
- `400` returns the documented status for malformed JSON or non-JSON bodies labeled as `application/json`, if the API distinguishes these from validation errors.
- Validate JSON response structure and content type.
- Verify field types, required properties, and any omitted optional fields.

## Additional Checks
- Boundary test for password length exactly 8 characters.
- Verify email normalization behavior if applicable (case sensitivity, whitespace trimming).
- Confirm leading/trailing whitespace handling in input fields.
- Check behavior for very long strings to assess input size handling.

## Exit Criteria
- All documented responses are observed and match schema.
- No critical security issues in authentication handling.
- Validation and error handling behave consistently for invalid inputs.
- Happy-path login reliably issues a token.