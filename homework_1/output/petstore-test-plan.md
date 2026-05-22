# QA Test Plan: Swagger Petstore API

## Scope
This test plan covers the API specification in `examples/petstore.json` (Swagger/OpenAPI 2.0), including all documented endpoints under `/v2`.

## Test strategy
For every endpoint, validate:
- Happy path behavior
- Negative/error handling
- Authentication/authorization behavior
- Security-oriented checks
- Contract/compliance checks for request and response shapes

## Common test data
- Valid pet ID: `1`
- Missing/non-existent pet ID: `999999`
- Valid order ID range: `1-10`
- Invalid IDs: `0`, `-1`, `abc`
- Valid status values: `available`, `pending`, `sold`
- Invalid status values: `unknown`, empty
- Valid tags: `tag1`, `tag2`
- Valid user: `user1`
- API key from spec example: `special-key`

## General contract checks
Apply as applicable to all responses:
- Correct HTTP status code
- Content-Type matches `produces`
- Response body schema matches spec
- Required fields are present and correctly typed
- No unexpected fields if strict schema validation is enabled
- No server stack traces or internal implementation details in errors
- Proper handling of unsupported media types and malformed JSON/XML/form data
- Ensure documented security schemes are enforced where declared

---

## Endpoint test cases

### 1) `POST /pet/{petId}/uploadImage`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Upload a valid image file for an existing pet ID with optional `additionalMetadata`.
- Expect `200` with `ApiResponse` schema containing `code`, `type`, `message`.

**Negative / validation**
- Missing `petId` path value → request should fail at routing/validation.
- `petId` is non-integer (`abc`) → `400`/validation error.
- Invalid file type or corrupt multipart payload → appropriate client error.
- Empty multipart body without file → verify behavior is documented/handled.

**Auth / access control**
- No OAuth token → `401`/`403` as applicable.
- Token without required scopes → `403`.
- Expired/invalid token → `401`.

**Security checks**
- Try filename/path traversal payloads in upload metadata.
- Attempt oversized file upload to verify size limits and safe rejection.
- Ensure uploaded content is not executed or interpreted.

**Contract checks**
- Multipart form fields accepted per spec: `additionalMetadata` string, `file` file.
- Response is JSON and conforms to `ApiResponse`.

---

### 2) `POST /pet`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Create a pet using a valid JSON body matching `Pet` with required fields `name` and `photoUrls`.
- Repeat with XML payload if supported by server.
- Expect documented success behavior or appropriate creation acceptance semantics.

**Negative / validation**
- Missing required field `name` → reject.
- Missing required field `photoUrls` → reject.
- Invalid `status` enum value → reject.
- Wrong data types for `id`, `photoUrls`, `tags` → reject.
- Invalid JSON/XML syntax → `400` or equivalent.
- Unsupported `Content-Type` → `415` if implemented.
- Spec notes `405 Invalid input`; verify invalid input returns the documented code.

**Auth / access control**
- Missing OAuth token → deny.
- Wrong scope → deny.
- Invalid token → deny.

**Security checks**
- Inject script/HTML in `name` and `photoUrls` to validate input sanitization and safe storage.
- Use very large arrays in `photoUrls`/`tags` to assess limits.
- Test mass-assignment style payloads with extra fields.

**Contract checks**
- Request body matches `Pet` schema.
- `produces` content types accepted for successful responses.
- Any error response should not leak server internals.

---

### 3) `PUT /pet`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Update an existing pet with a valid `Pet` body.
- Verify updated fields persist/reflect in subsequent fetches.

**Negative / validation**
- Missing required fields → reject.
- Invalid or missing `id` → expect `400`.
- Non-existent pet ID → expect `404`.
- Invalid payload structure/type mismatch → expect `405` validation exception or equivalent.
- Unsupported media type / malformed body → reject.

**Auth / access control**
- No token or insufficient scope → denied.

**Security checks**
- Attempt to update fields not intended for modification.
- Test SQL/NoSQL injection strings in text fields.
- Validate no unauthorized cross-tenant access if data isolation exists.

**Contract checks**
- Request/response follow `Pet` schema and declared content types.
- Error codes `400`, `404`, `405` are returned consistently where applicable.

---

### 4) `GET /pet/findByStatus`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Query with one valid status value.
- Query with multiple valid status values using `collectionFormat: multi`.
- Expect `200` and an array of `Pet` objects.

**Negative / validation**
- Missing required `status` parameter → `400`.
- Invalid status value → `400`.
- Empty status array or malformed repeated query params → reject.

**Auth / access control**
- Missing token → denied.
- Invalid/expired token or missing scope → denied.

**Security checks**
- Attempt injection via query parameter values.
- Ensure parameter parsing does not allow parameter pollution.

**Contract checks**
- Response is an array of `Pet`.
- Each returned item matches schema and status values are within enum.
- Verify `application/json` and `application/xml` handling if supported.

---

### 5) `GET /pet/findByTags`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)
**Note:** Endpoint is marked deprecated; verify deprecation is documented and does not break behavior.

**Happy path**
- Query with one valid tag.
- Query with multiple tags using `collectionFormat: multi`.
- Expect `200` with array of `Pet` objects.

**Negative / validation**
- Missing required `tags` parameter → `400`.
- Invalid/empty tag values → `400`.
- Malformed repeated query params → reject.

**Auth / access control**
- No token or wrong scope → denied.

**Security checks**
- Injection strings in tags parameter.
- Verify deprecated endpoint does not expose extra debug info.

**Contract checks**
- Response schema is an array of `Pet`.
- Confirm deprecation behavior is discoverable in docs/headers if implemented.

---

### 6) `GET /pet/{petId}`
**Security:** `api_key` in header

**Happy path**
- Request with valid `petId` and valid API key.
- Expect `200` with `Pet` schema.

**Negative / validation**
- Missing `petId` → invalid request.
- Non-integer `petId` → `400`.
- Unknown/non-existent `petId` → `404`.

**Auth / access control**
- Missing API key → denied.
- Invalid API key → denied.
- Confirm api key must be sent in the header and not in query/body.

**Security checks**
- Attempt header injection in `api_key` and path traversal-like inputs in `petId`.
- Verify no unauthorized data leakage on `404`.

**Contract checks**
- Response body conforms to `Pet` schema.
- Verify correct handling of `application/json` and `application/xml`.

---

### 7) `POST /pet/{petId}`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Update pet name/status with valid form data.
- Expect `405` only if the implementation purposely rejects; otherwise confirm actual documented behavior.

**Negative / validation**
- Missing `petId` → invalid.
- Invalid `petId` type → reject.
- Invalid form field values (e.g., unsupported `status`) → reject.
- Unsupported `Content-Type` instead of `application/x-www-form-urlencoded` → reject.

**Auth / access control**
- No token or missing scope → denied.

**Security checks**
- Form parameter injection tests for `name` and `status`.
- Very long form values to test truncation/limits.

**Contract checks**
- Enforce `application/x-www-form-urlencoded` only.
- Verify response code and body match implementation and spec expectations.

---

### 8) `DELETE /pet/{petId}`
**Security:** `petstore_auth` OAuth2 scope (`write:pets`, `read:pets`)

**Happy path**
- Delete an existing pet using a valid `petId`.
- If `api_key` header is used by implementation, send it as documented parameter and verify behavior.

**Negative / validation**
- Invalid `petId` (`abc`, `0`, `-1`) → `400`.
- Non-existent `petId` → `404`.
- Missing `petId` → invalid.

**Auth / access control**
- No OAuth token → denied.
- Missing required scope → denied.
- Verify behavior with/without optional `api_key` header as implemented.

**Security checks**
- Confirm deletion requires authorization and cannot delete arbitrary resources without permission.
- Test repeated delete idempotency expectations if applicable.

**Contract checks**
- Error responses match declared codes `400` and `404`.
- No sensitive data in response bodies.

---

### 9) `GET /store/inventory`
**Security:** `api_key` in header

**Happy path**
- Call with valid API key.
- Expect `200` and a JSON object mapping status strings to integer counts.

**Negative / validation**
- Missing API key → denied.
- Invalid API key → denied.

**Security checks**
- Ensure inventory counts do not leak restricted internal data beyond documented map.
- Confirm response handling resists oversized/abnormal key values if returned by server.

**Contract checks**
- Response is an object with additionalProperties of integer `int32`.
- Validate all values are integers.
- Content-Type is `application/json`.

---

### 10) `POST /store/order`
**Security:** none declared in spec

**Happy path**
- Submit a valid `Order` payload.
- Expect `200` and response body matching `Order` schema.

**Negative / validation**
- Missing required body → reject.
- Invalid `status` enum → `400`.
- Invalid `quantity`/type fields → `400`.
- Malformed JSON/XML → reject.
- Unsupported media type → reject.

**Auth / access control**
- Verify no auth is required per spec.
- Confirm endpoint does not unexpectedly accept privileged actions without controls if business rules say otherwise.

**Security checks**
- Injection strings in text-like fields.
- Boundary tests for large quantities, invalid dates, and oversized payloads.

**Contract checks**
- Request and response conform to `Order` schema.
- Verify `200` for successful order placement and `400` for invalid order.

---

### 11) `GET /store/order/{orderId}`
**Security:** none declared in spec

**Happy path**
- Fetch an existing order within valid range `1-10`.
- Expect `200` with `Order` schema.

**Negative / validation**
- `orderId` below minimum (`0`, `-1`) → `400`.
- `orderId` above maximum (`11`) → `400` or defined invalid response.
- Non-integer `orderId` → `400`.
- Non-existent order within valid range → `404`.

**Security checks**
- Ensure error messages do not expose internal exception details for out-of-range inputs.
- Validate path parameter handling against injection attempts.

**Contract checks**
- Enforce integer type, min `1`, max `10`.
- Response body matches `Order` schema.
- Verify documented error codes `400` and `404`.

---

### 12) `DELETE /store/order/{orderId}`
**Security:** none declared in spec

**Happy path**
- Delete an existing order with a valid positive integer `orderId`.
- Expect success behavior consistent with implementation; use `404` if already absent.

**Negative / validation**
- `orderId` below minimum (`0`, `-1`) → `400`.
- Non-integer `orderId` → `400`.
- Non-existent order → `404`.

**Security checks**
- Validate no unauthorized destructive behavior beyond intended scope.
- Confirm input validation prevents numeric overflow/format abuse.

**Contract checks**
- Enforce integer minimum `1`.
- Error responses match `400` and `404`.

---

### 13) `POST /user/createWithList`
**Security:** none declared in spec

**Happy path**
- Submit a valid array of `User` objects.
- Expect default successful operation response.

**Negative / validation**
- Empty array → verify accepted/rejected per business rules.
- Invalid user object inside array → reject.
- Wrong body type (object instead of array) → reject.
- Malformed JSON/XML → reject.

**Security checks**
- Test very large arrays to assess resource limits.
- Test input with malicious strings in user fields.

**Contract checks**
- Request body is an array of `User` items.
- Successful response uses declared default response behavior.
- Verify supported media types are handled.

---

### 14) `GET /user/{username}`
**Security:** none declared in spec

**Happy path**
- Fetch existing user `user1`.
- Expect `200` with `User` schema.

**Negative / validation**
- Missing username → invalid.
- Non-existent username → `404`.
- Invalid username format if validation exists → `400`.

**Security checks**
- Try path traversal-like strings and encoded characters in username.
- Ensure no user enumeration details are leaked in error messages.

**Contract checks**
- Response body conforms to `User` schema.
- Correct handling for `application/json` and `application/xml`.

---

### 15) `PUT /user/{username}`
**Security:** none declared in spec, but description says “only be done by the logged in user”

**Happy path**
- Update an existing user with valid `User` payload.
- Expect success behavior or documented response.

**Negative / validation**
- Missing body → reject.
- Invalid user fields / wrong types → `400`.
- Non-existent user → `404`.
- Username/body mismatch or invalid payload → reject.

**Auth / access control**
- Verify only authenticated/logged-in user can update as described.
- Attempt update as another user and confirm denial if auth is implemented.

**Security checks**
- Mass assignment tests on user fields.
- SQL/NoSQL injection strings in username and body properties.

**Contract checks**
- Request body matches `User` schema.
- Error codes `400` and `404` returned as documented.

---

### 16) `DELETE /user/{username}`
**Security:** none declared in spec, but description says “only be done by the logged in user”

**Happy path**
- Delete an existing user account.
- Expect success behavior or documented response.

**Negative / validation**
- Missing username → invalid.
- Non-existent user → `404`.
- Invalid username supplied → `400`.

**Auth / access control**
- Confirm only logged-in user can delete as described.
- Attempt deletion from another session/account and verify denial if implemented.

**Security checks**
- Ensure deletion endpoint cannot be abused for account takeover or user enumeration.

**Contract checks**
- Verify error codes `400` and `404`.
- Response does not disclose sensitive information.

---

### 17) `GET /user/login`
**Security:** none declared in spec

**Happy path**
- Login with valid username/password.
- Expect `200`, string response, and headers `X-Expires-After` and `X-Rate-Limit`.

**Negative / validation**
- Missing username or password → reject.
- Invalid credentials → `400`.
- Empty strings / whitespace-only values → reject.

**Security checks**
- Ensure password is not logged or echoed.
- Rate-limit and brute-force protection checks if implemented.
- Verify credentials are transmitted safely over HTTPS in normal usage.

**Contract checks**
- Response body is a string.
- Validate presence and types of response headers on success.
- Confirm `X-Expires-After` uses `date-time` format and `X-Rate-Limit` is integer.

---

### 18) `GET /user/logout`
**Security:** none declared in spec

**Happy path**
- Call logout for a logged-in session.
- Expect default successful operation response.

**Negative / validation**
- Call without an active session → verify graceful handling.
- Invalid session/token if applicable → handled safely.

**Security checks**
- Ensure logout invalidates current session/token if implementation uses sessions.
- Verify repeated logout requests are safe.

**Contract checks**
- Response matches default success behavior.
- No sensitive information returned.

---

### 19) `POST /user/createWithArray`
**Security:** none declared in spec

**Happy path**
- Submit valid array of `User` objects.
- Expect default successful operation response.

**Negative / validation**
- Body is not an array → reject.
- Array contains invalid user object → reject.
- Malformed body → reject.

**Security checks**
- Large payload and malicious field content tests.
- Verify array handling does not permit deserialization issues.

**Contract checks**
- Request body is array of `User` items.
- Successful response follows default response behavior.

---

### 20) `POST /user`
**Security:** none declared in spec, but description says “only be done by the logged in user”

**Happy path**
- Create a user with valid `User` payload.
- Expect default successful operation response.

**Negative / validation**
- Missing body → reject.
- Invalid field types or missing required business fields → reject.
- Malformed JSON/XML → reject.

**Auth / access control**
- Verify only logged-in user can create as described, if auth is enforced.
- Attempt creation without session/auth if implementation requires it.

**Security checks**
- Input sanitization for username, email, password, and phone.
- Test weak password acceptance only if policy exists; otherwise ensure no server-side leakage.

**Contract checks**
- Request body conforms to `User` schema.
- Default success response is returned as documented.

---

## Non-functional / cross-cutting checks
- Verify scheme support for both `http` and `https` as deployed, with secure defaults.
- Confirm content negotiation for JSON and XML where documented.
- Validate consistent error handling and status codes across endpoints.
- Check API key and OAuth2 protection are not bypassable via alternate encodings or parameter placement.
- Ensure deprecated endpoint behavior is still stable and documented.
- Confirm response schemas match definitions: `ApiResponse`, `Pet`, `Order`, `User`, and inventory map.

## Exit criteria
- Every endpoint has passed happy path, negative, auth, security, and contract checks.
- No critical/high-severity defects remain open.
- All deviations from spec are documented with severity and repro steps.
