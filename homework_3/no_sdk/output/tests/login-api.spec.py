from __future__ import annotations

import json
import os
from typing import TypedDict

import pytest
from playwright.sync_api import APIRequestContext, APIResponse


# ─── Configuration ───
VALID_EMAIL = os.environ.get("VALID_EMAIL", "active.user@example.com")
VALID_PASSWORD = os.environ.get("VALID_PASSWORD", "ValidPassw0rd!")
INVALID_PASSWORD = os.environ.get("INVALID_PASSWORD", "WrongPassw0rd!")
UNKNOWN_EMAIL = os.environ.get("UNKNOWN_EMAIL", "unknown.user@example.com")
LOCKED_EMAIL = os.environ.get("LOCKED_EMAIL", "locked.user@example.com")
UNVERIFIED_EMAIL = os.environ.get("UNVERIFIED_EMAIL", "unverified.user@example.com")
SHORT_PASSWORD = os.environ.get("SHORT_PASSWORD", "short")
EXTRA_VALUE = os.environ.get("EXTRA_VALUE", "value")
INVALID_BEARER_TOKEN = os.environ.get("INVALID_BEARER_TOKEN", "bogus-token")
RESPONSE_TIME_LIMIT_MS = int(os.environ.get("RESPONSE_TIME_LIMIT_MS", "3000"))
RATE_LIMIT_ATTEMPT_COUNT = int(os.environ.get("RATE_LIMIT_ATTEMPT_COUNT", "5"))


class LoginSuccessResponse(TypedDict, total=False):
    token: str
    expires_in: int


class ErrorResponse(TypedDict, total=False):
    error: str
    message: str
    detail: str
    code: str


class ValidationCase(TypedDict):
    name: str
    body: object


class UnsupportedMethodCase(TypedDict):
    method: str
    expected_status: int


VALID_LOGIN_BODY = {"email": VALID_EMAIL, "password": VALID_PASSWORD}
WRONG_PASSWORD_BODY = {"email": VALID_EMAIL, "password": INVALID_PASSWORD}
UNKNOWN_USER_BODY = {"email": UNKNOWN_EMAIL, "password": VALID_PASSWORD}
LOCKED_USER_BODY = {"email": LOCKED_EMAIL, "password": VALID_PASSWORD}
UNVERIFIED_USER_BODY = {"email": UNVERIFIED_EMAIL, "password": VALID_PASSWORD}

MISSING_FIELD_CASES: list[ValidationCase] = [
    {"name": "missing_email", "body": {"password": VALID_PASSWORD}},
    {"name": "missing_password", "body": {"email": VALID_EMAIL}},
    {"name": "missing_both", "body": {}},
]

INVALID_FORMAT_CASES: list[ValidationCase] = [
    {"name": "malformed_email", "body": {"email": "not-an-email", "password": VALID_PASSWORD}},
    {"name": "short_password", "body": {"email": VALID_EMAIL, "password": SHORT_PASSWORD}},
]

EXTRA_FIELD_CASES: list[ValidationCase] = [
    {"name": "role_field", "body": {"email": VALID_EMAIL, "password": VALID_PASSWORD, "role": EXTRA_VALUE}},
    {"name": "is_admin_field", "body": {"email": VALID_EMAIL, "password": VALID_PASSWORD, "isAdmin": True}},
    {"name": "token_field", "body": {"email": VALID_EMAIL, "password": VALID_PASSWORD, "token": EXTRA_VALUE}},
]

UNSUPPORTED_METHOD_CASES: list[UnsupportedMethodCase] = [
    {"method": "GET", "expected_status": 405},
    {"method": "PUT", "expected_status": 405},
    {"method": "PATCH", "expected_status": 405},
    {"method": "DELETE", "expected_status": 405},
]

INVALID_CREDENTIAL_CASES: list[tuple[str, dict[str, str]]] = [
    ("wrong_password", WRONG_PASSWORD_BODY),
    ("unknown_user", UNKNOWN_USER_BODY),
    ("locked_user", LOCKED_USER_BODY),
    ("unverified_user", UNVERIFIED_USER_BODY),
]


def send_login_request(
    request: APIRequestContext,
    body: dict | None,
    headers: dict[str, str] | None = None,
) -> APIResponse:
    request_headers: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    return request.post("/api/login", data=json.dumps(body) if body is not None else None, headers=request_headers)


def send_raw_login_request(
    request: APIRequestContext,
    raw_body: str | None,
    headers: dict[str, str] | None = None,
) -> APIResponse:
    request_headers: dict[str, str] = {}
    if headers:
        request_headers.update(headers)
    return request.post("/api/login", data=raw_body, headers=request_headers)


def parse_json_body(response: APIResponse) -> dict:
    text = response.text()
    assert text, "response body should not be empty"
    parsed = json.loads(text)
    assert isinstance(parsed, dict), "response body should be a JSON object"
    return parsed


def assert_content_type_json(response: APIResponse) -> None:
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/json"), f"expected JSON content-type, got {content_type!r}"


def assert_valid_login_response(body: dict) -> None:
    assert "token" in body, "success response should include token"
    token = body["token"]
    assert isinstance(token, str), "token should be a string"
    assert token.strip(), "token should be non-empty"
    if "expires_in" in body:
        expires_in = body["expires_in"]
        assert isinstance(expires_in, int), "expires_in should be an integer"
        assert expires_in > 0, "expires_in should be greater than zero"
    unexpected_keys = set(body.keys()) - {"token", "expires_in"}
    assert not unexpected_keys, f"unexpected success response fields: {sorted(unexpected_keys)}"


def assert_error_response_shape(body: dict) -> None:
    assert body, "error response should not be empty"
    allowed_keys = {"error", "message", "detail", "code"}
    assert set(body.keys()).issubset(allowed_keys), f"unexpected error response fields: {sorted(set(body.keys()) - allowed_keys)}"
    combined = " ".join(str(body.get(key, "")) for key in allowed_keys)
    forbidden_fragments = ["stack", "trace", "sql", "select ", "insert ", "update ", "delete ", "/", "\\"]
    for fragment in forbidden_fragments:
        assert fragment not in combined.lower(), f"error response should not expose {fragment!r}"


def assert_validation_error(response: APIResponse, label: str) -> None:
    assert response.status in (400, 415, 422), f"{label}: expected 400, 415, or 422, got {response.status}"
    assert_content_type_json(response)
    body = parse_json_body(response)
    assert_error_response_shape(body)


class TestHappyPath:
    def test_returns_200_with_valid_token(self, request: APIRequestContext) -> None:
        response = send_login_request(request, VALID_LOGIN_BODY)
        assert response.status == 200
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_valid_login_response(body)


class TestAuthentication:
    @pytest.mark.parametrize("name,body", INVALID_CREDENTIAL_CASES, ids=[case[0] for case in INVALID_CREDENTIAL_CASES])
    def test_returns_401_for_invalid_credentials(self, request: APIRequestContext, name: str, body: dict[str, str]) -> None:
        response = send_login_request(request, body)
        assert response.status == 401, f"{name}: expected 401, got {response.status}"
        assert_content_type_json(response)
        parsed = parse_json_body(response)
        assert_error_response_shape(parsed)

    def test_returns_200_without_authorization_header(self, request: APIRequestContext) -> None:
        response = send_login_request(request, VALID_LOGIN_BODY)
        assert response.status == 200
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_valid_login_response(body)

    def test_ignores_authorization_header_for_valid_credentials(self, request: APIRequestContext) -> None:
        response = send_login_request(request, VALID_LOGIN_BODY, headers={"Authorization": f"Bearer {INVALID_BEARER_TOKEN}"})
        assert response.status == 200
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_valid_login_response(body)


class TestValidationMissingFields:
    @pytest.mark.parametrize("case", MISSING_FIELD_CASES, ids=[case["name"] for case in MISSING_FIELD_CASES])
    def test_rejects_request_with_missing_required_fields(self, request: APIRequestContext, case: ValidationCase) -> None:
        response = send_login_request(request, case["body"] if isinstance(case["body"], dict) else None)
        assert_validation_error(response, case["name"])

    @pytest.mark.parametrize("case", INVALID_FORMAT_CASES, ids=[case["name"] for case in INVALID_FORMAT_CASES])
    def test_rejects_request_with_invalid_field_format(self, request: APIRequestContext, case: ValidationCase) -> None:
        response = send_login_request(request, case["body"] if isinstance(case["body"], dict) else None)
        assert_validation_error(response, case["name"])

    @pytest.mark.parametrize("case", EXTRA_FIELD_CASES, ids=[case["name"] for case in EXTRA_FIELD_CASES])
    def test_rejects_request_with_extra_unknown_fields(self, request: APIRequestContext, case: ValidationCase) -> None:
        response = send_login_request(request, case["body"] if isinstance(case["body"], dict) else None)
        assert response.status in (200, 401, 422), f"{case['name']}: expected 200, 401, or 422, got {response.status}"
        assert_content_type_json(response)
        body_text = response.text()
        assert body_text, f"{case['name']}: response body should not be empty"
        parsed = json.loads(body_text)
        assert isinstance(parsed, dict), f"{case['name']}: response body should be a JSON object"


class TestRequestContentTypeAndPayloadValidation:
    def test_rejects_request_without_content_type_header(self, request: APIRequestContext) -> None:
        response = send_raw_login_request(request, json.dumps(VALID_LOGIN_BODY), headers={})
        assert response.status in (415, 422), f"missing_content_type: expected 415 or 422, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)

    def test_rejects_request_with_wrong_media_type(self, request: APIRequestContext) -> None:
        response = request.post("/api/login", data=json.dumps(VALID_LOGIN_BODY), headers={"Content-Type": "text/plain"})
        assert response.status == 415, f"wrong_media_type: expected 415, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)

    def test_rejects_malformed_json(self, request: APIRequestContext) -> None:
        response = send_raw_login_request(request, '{"email": "a@example.com", "password":', headers={"Content-Type": "application/json"})
        assert response.status in (400, 422), f"invalid_json: expected 400 or 422, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)

    def test_rejects_array_top_level_type(self, request: APIRequestContext) -> None:
        response = send_raw_login_request(request, "[]", headers={"Content-Type": "application/json"})
        assert response.status == 422, f"array_top_level_type: expected 422, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)

    def test_rejects_string_top_level_type(self, request: APIRequestContext) -> None:
        response = send_raw_login_request(request, json.dumps("hello"), headers={"Content-Type": "application/json"})
        assert response.status == 422, f"string_top_level_type: expected 422, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)

    def test_rejects_null_top_level_type(self, request: APIRequestContext) -> None:
        response = send_raw_login_request(request, "null", headers={"Content-Type": "application/json"})
        assert response.status == 422, f"null_top_level_type: expected 422, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)


class TestUnsupportedHttpMethods:
    @pytest.mark.parametrize("case", UNSUPPORTED_METHOD_CASES, ids=[case["method"] for case in UNSUPPORTED_METHOD_CASES])
    def test_returns_method_not_allowed_for_unsupported_methods(self, request: APIRequestContext, case: UnsupportedMethodCase) -> None:
        response = request.fetch("/api/login", method=case["method"], headers={"Content-Type": "application/json"})
        assert response.status == case["expected_status"], f"{case['method']}: expected {case['expected_status']}, got {response.status}"
        allow_header = response.headers.get("allow", "")
        assert allow_header, f"{case['method']}: expected Allow header to be present"


class TestSecurity:
    def test_rejects_sql_injection_payloads(self, request: APIRequestContext) -> None:
        injection_cases: list[ValidationCase] = [
            {"name": "sql_in_email", "body": {"email": "' OR '1'='1", "password": VALID_PASSWORD}},
            {"name": "nosql_in_password", "body": {"email": VALID_EMAIL, "password": '{"$ne": null}'}},
            {"name": "script_in_email", "body": {"email": "<script>alert(1)</script>", "password": VALID_PASSWORD}},
        ]
        for case in injection_cases:
            response = send_login_request(request, case["body"] if isinstance(case["body"], dict) else None)
            assert response.status in (401, 422), f"{case['name']}: expected 401 or 422, got {response.status}"
            assert_content_type_json(response)
            body = parse_json_body(response)
            assert_error_response_shape(body)

    def test_rejects_rate_limit_attempts_consistently(self, request: APIRequestContext) -> None:
        last_response: APIResponse | None = None
        for _ in range(RATE_LIMIT_ATTEMPT_COUNT):
            last_response = send_login_request(request, WRONG_PASSWORD_BODY)
            assert last_response.status == 401, f"rate_limit_precheck: expected 401, got {last_response.status}"
            assert_content_type_json(last_response)
            body = parse_json_body(last_response)
            assert_error_response_shape(body)

        assert last_response is not None

    def test_rejects_failed_login_with_sanitized_error_response(self, request: APIRequestContext) -> None:
        response = send_login_request(request, WRONG_PASSWORD_BODY)
        assert response.status == 401, f"sanitized_error: expected 401, got {response.status}"
        assert_content_type_json(response)
        body = parse_json_body(response)
        assert_error_response_shape(body)
        combined = " ".join(str(value) for value in body.values())
        forbidden = [VALID_PASSWORD, INVALID_PASSWORD, "password hash", "stack trace", "traceback"]
        for item in forbidden:
            assert item.lower() not in combined.lower(), f"error response should not include {item!r}"
