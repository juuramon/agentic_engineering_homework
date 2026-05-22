import { test, expect, APIRequestContext, APIResponse } from '@playwright/test';

// ─── Configuration ───
const VALID_EMAIL = process.env.LOGIN_API_VALID_EMAIL ?? 'valid@example.com';
const VALID_PASSWORD = process.env.LOGIN_API_VALID_PASSWORD ?? 'ValidPass123!';
const INVALID_EMAIL = process.env.LOGIN_API_INVALID_EMAIL ?? 'invalid@example.com';
const INVALID_PASSWORD = process.env.LOGIN_API_INVALID_PASSWORD ?? 'WrongPass123!';
const BEARER_TOKEN = process.env.LOGIN_API_BEARER_TOKEN ?? 'test-bearer-token';
const RESPONSE_TIME_LIMIT_MS = 3000;
const RATE_LIMIT_ATTEMPTS = Number(process.env.LOGIN_API_RATE_LIMIT_ATTEMPTS ?? '5');
const RATE_LIMIT_PAYLOAD = process.env.LOGIN_API_RATE_LIMIT_PAYLOAD ?? 'rate-limit@example.com';
const LONG_STRING_LENGTH = 4096;
const CONTENT_TYPE_JSON = 'application/json';
const CACHE_CONTROL_NO_STORE = 'no-store';
const EXPECTED_SUCCESS_STATUS = 200;
const EXPECTED_UNAUTHORIZED_STATUS = 401;
const EXPECTED_UNPROCESSABLE_STATUS = 422;
const EXPECTED_BAD_REQUEST_STATUS = 400;
const EXPECTED_UNSUPPORTED_MEDIA_STATUS = 415;
const EXPECTED_TOO_MANY_REQUESTS_STATUS = 429;

interface LoginSuccessResponse {
  token: string;
  expires_in?: number;
}

interface LoginErrorResponse {
  message?: string;
  error?: string;
  errors?: Array<{ field?: string; message?: string }>;
  detail?: string;
}

async function sendRequest(
  request: APIRequestContext,
  body: unknown,
  headers?: Record<string, string>,
): Promise<APIResponse> {
  return request.post('/api/login', {
    data: body as never,
    headers,
  });
}

async function parseJsonBody<T = unknown>(response: APIResponse): Promise<T> {
  return (await response.json()) as T;
}

function expectValidResponse(body: LoginSuccessResponse): void {
  expect(typeof body.token === 'string' && body.token.length > 0, 'token should be a non-empty string').toBe(true);
  if (body.expires_in !== undefined) {
    expect(Number.isInteger(body.expires_in), 'expires_in should be an integer when present').toBe(true);
  }
}

function expectValidationError(body: LoginErrorResponse): void {
  const hasKnownShape =
    typeof body === 'object' &&
    body !== null &&
    (typeof body.message === 'string' || typeof body.error === 'string' || Array.isArray(body.errors) || typeof body.detail === 'string');
  expect(hasKnownShape, 'validation error response should include a recognizable error shape').toBe(true);
}

function buildLoginBody(email?: string, password?: string): Record<string, string> {
  const payload: Record<string, string> = {};
  if (email !== undefined) payload.email = email;
  if (password !== undefined) payload.password = password;
  return payload;
}

async function expectNoServerError(response: APIResponse): Promise<void> {
  expect(response.status() < 500, `expected no server error, got ${response.status()}`).toBe(true);
}

async function expectJsonContentType(response: APIResponse): Promise<void> {
  const contentType = response.headers()['content-type'] ?? '';
  expect(contentType.toLowerCase().includes(CONTENT_TYPE_JSON), `expected JSON content-type, got ${contentType}`).toBe(true);
}

async function expectNoSensitiveEcho(responseBody: string): Promise<void> {
  expect(responseBody.includes('password'), 'response body should not echo password').toBe(false);
}

const invalidEmails = [
  { label: 'malformed email abc', value: 'abc' },
  { label: 'malformed email user@', value: 'user@' },
];

const invalidPasswords = [
  { label: 'too short password length 1', value: 'a' },
  { label: 'too short password length 7', value: '1234567' },
];

const injectionPayloads = [
  { label: 'sql meta characters in email', email: "' OR 1=1 --", password: 'ValidPass123!' },
  { label: 'sql meta characters in password', email: VALID_EMAIL, password: "' OR 1=1 --" },
  { label: 'long email string', email: `${'a'.repeat(LONG_STRING_LENGTH)}@example.com`, password: VALID_PASSWORD },
  { label: 'long password string', email: VALID_EMAIL, password: 'a'.repeat(LONG_STRING_LENGTH) },
];

const invalidContentTypes = [
  { label: 'missing content-type', headers: {} },
  { label: 'text/plain content-type', headers: { 'Content-Type': 'text/plain' } },
];

test.describe('POST /api/login', () => {
  test.describe('Happy path', () => {
    test('valid credentials return a session token', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });

      expect(response.status()).toBe(EXPECTED_SUCCESS_STATUS);
      await expectJsonContentType(response);
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expectValidResponse(body);
      expect(Object.keys(body).every((key) => ['token', 'expires_in'].includes(key)), 'success payload should not include unexpected fields').toBe(true);
      const cacheControl = response.headers()['cache-control'] ?? '';
      if (cacheControl) {
        expect(cacheControl.toLowerCase().includes(CACHE_CONTROL_NO_STORE), `expected Cache-Control to include no-store, got ${cacheControl}`).toBe(true);
      }
      await expectNoServerError(response);
    });

    test('successful response is valid JSON and parseable', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });

      expect(response.status()).toBe(EXPECTED_SUCCESS_STATUS);
      await expectJsonContentType(response);
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expectValidResponse(body);
    });
  });

  test.describe('Negative and validation', () => {
    test('missing email returns 422', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(undefined, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_UNPROCESSABLE_STATUS);
      const body = await parseJsonBody<LoginErrorResponse>(response);
      expectValidationError(body);
    });

    test('missing password returns 422', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, undefined), { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_UNPROCESSABLE_STATUS);
      const body = await parseJsonBody<LoginErrorResponse>(response);
      expectValidationError(body);
    });

    for (const invalidEmail of invalidEmails) {
      test(`${invalidEmail.label} returns 422`, async ({ request }) => {
        const response = await sendRequest(request, buildLoginBody(invalidEmail.value, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
        expect(response.status()).toBe(EXPECTED_UNPROCESSABLE_STATUS);
        const body = await parseJsonBody<LoginErrorResponse>(response);
        expectValidationError(body);
      });
    }

    for (const invalidPassword of invalidPasswords) {
      test(`${invalidPassword.label} returns 422`, async ({ request }) => {
        const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, invalidPassword.value), { 'Content-Type': CONTENT_TYPE_JSON });
        expect(response.status()).toBe(EXPECTED_UNPROCESSABLE_STATUS);
        const body = await parseJsonBody<LoginErrorResponse>(response);
        expectValidationError(body);
      });
    }

    test('empty request body returns 422', async ({ request }) => {
      const response = await sendRequest(request, {}, { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_UNPROCESSABLE_STATUS);
      const body = await parseJsonBody<LoginErrorResponse>(response);
      expectValidationError(body);
    });

    test('malformed JSON body returns a client error', async ({ request }) => {
      const response = await request.post('/api/login', {
        data: '{"email":"abc","password":"12345678"',
        headers: { 'Content-Type': CONTENT_TYPE_JSON },
      });
      expect([EXPECTED_BAD_REQUEST_STATUS, EXPECTED_UNPROCESSABLE_STATUS].includes(response.status()), `expected 400 or 422, got ${response.status()}`).toBe(true);
      await expectNoServerError(response);
    });

    test('wrong credentials return 401', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(INVALID_EMAIL, INVALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_UNAUTHORIZED_STATUS);
      const body = await parseJsonBody<LoginErrorResponse>(response);
      expectValidationError(body);
    });
  });

  test.describe('Authentication and authorization', () => {
    test('login does not require prior auth', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_SUCCESS_STATUS);
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expectValidResponse(body);
    });

    test('bearer token is ignored', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), {
        'Content-Type': CONTENT_TYPE_JSON,
        Authorization: `Bearer ${BEARER_TOKEN}`,
      });
      expect(response.status()).toBe(EXPECTED_SUCCESS_STATUS);
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expectValidResponse(body);
    });
  });

  test.describe('Security', () => {
    test('credential handling does not echo password', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      const rawBody = await response.text();
      await expectNoSensitiveEcho(rawBody);
    });

    for (const payload of injectionPayloads) {
      test(`${payload.label} is handled safely`, async ({ request }) => {
        const response = await sendRequest(request, buildLoginBody(payload.email, payload.password), { 'Content-Type': CONTENT_TYPE_JSON });
        await expectNoServerError(response);
        expect([EXPECTED_UNPROCESSABLE_STATUS, EXPECTED_UNAUTHORIZED_STATUS].includes(response.status()), `expected 422 or 401, got ${response.status()}`).toBe(true);
      });
    }

    for (const contentTypeCase of invalidContentTypes) {
      test(`${contentTypeCase.label} returns a client error`, async ({ request }) => {
        const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), contentTypeCase.headers);
        expect([EXPECTED_UNSUPPORTED_MEDIA_STATUS, EXPECTED_UNPROCESSABLE_STATUS, EXPECTED_BAD_REQUEST_STATUS].includes(response.status()), `expected 415, 422, or 400, got ${response.status()}`).toBe(true);
        await expectNoServerError(response);
      });
    }

    test('repeated invalid login attempts do not cause 5xx responses', async ({ request }) => {
      let sawRateLimit = false;
      for (let attempt = 0; attempt < RATE_LIMIT_ATTEMPTS; attempt += 1) {
        const response = await sendRequest(request, buildLoginBody(RATE_LIMIT_PAYLOAD, INVALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
        await expectNoServerError(response);
        if (response.status() === EXPECTED_TOO_MANY_REQUESTS_STATUS) {
          sawRateLimit = true;
        } else {
          expect([EXPECTED_UNAUTHORIZED_STATUS, EXPECTED_UNPROCESSABLE_STATUS].includes(response.status()), `expected 401, 422, or 429, got ${response.status()}`).toBe(true);
        }
      }
      expect(true, sawRateLimit ? 'rate limiting observed' : 'rate limiting not observed; no 5xx responses observed').toBe(true);
    });
  });

  test.describe('Contract and schema', () => {
    test('200 response matches contract schema', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      expect(response.status()).toBe(EXPECTED_SUCCESS_STATUS);
      await expectJsonContentType(response);
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expectValidResponse(body);
    });

    test('documented response codes are returned for defined scenarios', async ({ request }) => {
      const scenarios: Array<{ label: string; body: Record<string, string>; expected: number }> = [
        { label: 'success', body: buildLoginBody(VALID_EMAIL, VALID_PASSWORD), expected: EXPECTED_SUCCESS_STATUS },
        { label: 'wrong credentials', body: buildLoginBody(INVALID_EMAIL, INVALID_PASSWORD), expected: EXPECTED_UNAUTHORIZED_STATUS },
        { label: 'missing email', body: buildLoginBody(undefined, VALID_PASSWORD), expected: EXPECTED_UNPROCESSABLE_STATUS },
      ];

      for (const scenario of scenarios) {
        const response = await sendRequest(request, scenario.body, { 'Content-Type': CONTENT_TYPE_JSON });
        expect(response.status()).toBe(scenario.expected);
      }
    });

    test('successful response contains no unexpected fields', async ({ request }) => {
      const response = await sendRequest(request, buildLoginBody(VALID_EMAIL, VALID_PASSWORD), { 'Content-Type': CONTENT_TYPE_JSON });
      const body = await parseJsonBody<LoginSuccessResponse>(response);
      expect(Object.keys(body).every((key) => key === 'token' || key === 'expires_in'), 'response should contain only documented fields').toBe(true);
    });
  });
});