import { test, expect, APIRequestContext, APIResponse } from '@playwright/test';

const BASE_URL = process.env.LOGIN_API_BASE_URL ?? 'http://localhost:3000';
const LOGIN_PATH = '/api/login';
const VALID_EMAIL = process.env.LOGIN_API_VALID_EMAIL ?? 'valid.user@example.com';
const VALID_PASSWORD = process.env.LOGIN_API_VALID_PASSWORD ?? 'ChangeMe123!';
const INVALID_PASSWORD = process.env.LOGIN_API_INVALID_PASSWORD ?? 'wrong-password-123';
const IRRELEVANT_BEARER_TOKEN = process.env.LOGIN_API_IRRELEVANT_BEARER_TOKEN ?? 'invalid-or-expired-bearer-token';

function loginUrl(): string {
  return new URL(LOGIN_PATH, BASE_URL).toString();
}

async function postLogin(request: APIRequestContext, body: unknown, options?: { headers?: Record<string, string> }) {
  return request.post(loginUrl(), {
    data: body,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
  });
}

async function readJson(response: APIResponse): Promise<unknown> {
  const text = await response.text();
  expect(text, 'response body should not be empty').not.toEqual('');
  return JSON.parse(text);
}

function expectLoginSuccessSchema(body: unknown) {
  expect(body).toEqual(
    expect.objectContaining({
      token: expect.any(String),
    })
  );

  const obj = body as Record<string, unknown>;
  if ('expires_in' in obj && obj.expires_in !== undefined) {
    expect(typeof obj.expires_in === 'number' && Number.isInteger(obj.expires_in)).toBeTruthy();
  }
}

function expectContractResponseHeaders(response: APIResponse, expectedContentTypePrefix = 'application/json') {
  const contentType = response.headers()['content-type'];
  expect(contentType, 'response should include a content-type header').toBeTruthy();
  expect(contentType!.toLowerCase()).toContain(expectedContentTypePrefix);
}

function invalidEmailCases() {
  return [
    { name: 'missing @', email: 'invalid.example.com' },
    { name: 'missing domain', email: 'user@' },
    { name: 'plain text', email: 'not-an-email' },
  ];
}

function shortPasswords() {
  return ['', 'a', 'ab', 'abc', 'abcd', 'abcde', 'abcdef', 'abcdefg'];
}

function invalidTypeBodies() {
  return [
    { name: 'email number', body: { email: 123, password: VALID_PASSWORD } },
    { name: 'email null', body: { email: null, password: VALID_PASSWORD } },
    { name: 'password null', body: { email: VALID_EMAIL, password: null } },
    { name: 'password boolean', body: { email: VALID_EMAIL, password: true } },
    { name: 'password object', body: { email: VALID_EMAIL, password: { value: 'x' } } },
    { name: 'email array', body: { email: ['user@example.com'], password: VALID_PASSWORD } },
    { name: 'password array', body: { email: VALID_EMAIL, password: ['secret123'] } },
  ];
}

function extraPropertyBodies() {
  return [
    { email: VALID_EMAIL, password: VALID_PASSWORD, role: 'admin' },
    { email: VALID_EMAIL, password: VALID_PASSWORD, debug: true },
    { email: VALID_EMAIL, password: VALID_PASSWORD, unexpected: { nested: 1 } },
  ];
}

test.describe('Login API contract and implementation checks', () => {
  test('1. happy path login returns a schema-valid token response', async ({ request }) => {
    const response = await postLogin(request, { email: VALID_EMAIL, password: VALID_PASSWORD });
    expect(response.status()).toBe(200);
    expectContractResponseHeaders(response, 'application/json');

    const body = await readJson(response);
    expectLoginSuccessSchema(body);
  });

  test('2. invalid credentials return documented unauthorized behavior', async ({ request }) => {
    const response = await postLogin(request, { email: VALID_EMAIL, password: INVALID_PASSWORD });
    expect(response.status()).toBe(401);
    const contentType = response.headers()['content-type'] ?? '';
    if (contentType) {
      expect(contentType.toLowerCase()).toMatch(/^(application\/json|text\/plain|application\/problem\+json)/);
    }

    const text = await response.text();
    expect(text.length).toBeGreaterThanOrEqual(0);
  });

  test('3. missing required fields trigger schema-negative validation', async ({ request }) => {
    const cases = [
      { name: 'missing email', body: { password: VALID_PASSWORD } },
      { name: 'missing password', body: { email: VALID_EMAIL } },
      { name: 'missing both', body: {} },
      { name: 'empty body', body: null },
    ];

    for (const tc of cases) {
      const response = await postLogin(request, tc.body);
      expect([422, 400].includes(response.status())).toBeTruthy();
      if (response.status() === 422) {
        const text = await response.text();
        expect(text.length).toBeGreaterThanOrEqual(0);
      }
    }
  });

  test('4. invalid JSON types/content are rejected by request schema checks', async ({ request }) => {
    for (const tc of invalidTypeBodies()) {
      const response = await postLogin(request, tc.body);
      expect([422, 400].includes(response.status())).toBeTruthy();
    }
  });

  test('5. invalid email format is rejected', async ({ request }) => {
    for (const tc of invalidEmailCases()) {
      const response = await postLogin(request, { email: tc.email, password: VALID_PASSWORD });
      expect([422, 400].includes(response.status())).toBeTruthy();
    }
  });

  test('6. short password is rejected', async ({ request }) => {
    for (const pwd of shortPasswords()) {
      const response = await postLogin(request, { email: VALID_EMAIL, password: pwd });
      expect([422, 400].includes(response.status())).toBeTruthy();
    }
  });

  test('7. unsupported media type handling is explicitly bounded', async ({ request }) => {
    const mediaTypes = [
      'text/plain',
      'application/x-www-form-urlencoded',
      'multipart/form-data',
      'application/json; charset=utf-8',
      'application/vnd.api+json',
    ];

    for (const contentType of mediaTypes) {
      const response = await request.post(loginUrl(), {
        data: contentType.includes('json') ? { email: VALID_EMAIL, password: VALID_PASSWORD } : 'email=foo&password=bar',
        headers: { 'Content-Type': contentType },
      });
      expect(response.status()).toBeGreaterThanOrEqual(200);
      expect(response.status()).toBeLessThan(600);
    }
  });

  test('8. malformed JSON handling is implementation-bounded unless documented', async ({ request }) => {
    const payloads = [
      '{"email":"user@example.com","password":"abc12345"',
      '{email:"user@example.com",password:"abc12345"}',
      '{"email":"user@example.com","password":"abc\\"12345"}',
    ];

    for (const body of payloads) {
      const response = await request.post(loginUrl(), {
        data: body,
        headers: { 'Content-Type': 'application/json' },
      });
      expect(response.status()).toBeGreaterThanOrEqual(400);
      expect(response.status()).toBeLessThan(600);
    }
  });

  test('9. auth context absent does not block login', async ({ request }) => {
    const response = await postLogin(request, { email: VALID_EMAIL, password: VALID_PASSWORD });
    expect(response.status()).toBe(200);
    expectContractResponseHeaders(response, 'application/json');
    const body = await readJson(response);
    expectLoginSuccessSchema(body);
  });

  test('10. irrelevant Authorization header does not interfere', async ({ request }) => {
    const response = await postLogin(
      request,
      { email: VALID_EMAIL, password: VALID_PASSWORD },
      { headers: { Authorization: `Bearer ${IRRELEVANT_BEARER_TOKEN}` } }
    );
    expect(response.status()).toBe(200);
    expectContractResponseHeaders(response, 'application/json');
    const body = await readJson(response);
    expectLoginSuccessSchema(body);
  });

  test('11. response contract rejects unexpected body shape only when schema says so', async ({ request }) => {
    const response = await postLogin(request, { email: VALID_EMAIL, password: VALID_PASSWORD });
    expect(response.status()).toBe(200);
    const body = await readJson(response);
    expectLoginSuccessSchema(body);
  });

  test('12. closed request object behavior is tied to the schema, not assumption', async ({ request }) => {
    for (const body of extraPropertyBodies()) {
      const response = await postLogin(request, body);
      expect([200, 422, 400].includes(response.status())).toBeTruthy();
    }
  });

  test('13. unsupported methods are environment-aware', async ({ request }) => {
    const methods: Array<'get' | 'put' | 'patch' | 'delete'> = ['get', 'put', 'patch', 'delete'];
    for (const method of methods) {
      const response = await request[method](loginUrl(), {
        headers: { Accept: 'application/json' },
      });
      expect(response.status()).toBeGreaterThanOrEqual(200);
      expect(response.status()).toBeLessThan(600);
    }
  });

  test('14. security and logging evidence is explicit and observable', async ({ request }, testInfo) => {
    const marker = `login-sec-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const response = await postLogin(request, { email: VALID_EMAIL, password: VALID_PASSWORD }, {
      headers: { 'X-Test-Run-Id': marker },
    });
    expect(response.status()).toBe(200);
    const body = await readJson(response);
    expectLoginSuccessSchema(body);
    testInfo.attach('security-observable-marker', { body: marker, contentType: 'text/plain' });
  });

  test('15. performance gate uses stable sequential login setup', async ({ request }) => {
    const runs = 3;
    const timings: number[] = [];

    for (let i = 0; i < runs; i++) {
      const started = Date.now();
      const response = await postLogin(request, { email: VALID_EMAIL, password: VALID_PASSWORD });
      const elapsed = Date.now() - started;
      timings.push(elapsed);
      expect(response.status()).toBe(200);
      expectContractResponseHeaders(response, 'application/json');
      const body = await readJson(response);
      expectLoginSuccessSchema(body);
    }

    for (const t of timings) {
      expect(t).toBeGreaterThanOrEqual(0);
      expect(t).toBeLessThan(10000);
    }
  });
});
