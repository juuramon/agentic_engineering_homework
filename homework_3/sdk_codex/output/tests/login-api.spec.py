from __future__ import annotations

import json
import os
from typing import TypedDict

import pytest
from playwright.sync_api import APIRequestContext, APIResponse


# ─── Configuration ───
VALID_EMAIL = os.environ.get("LOGIN_VALID_EMAIL", "valid.user@example.com")
VALID_PASSWORD = os.environ.get("LOGIN_VALID_PASSWORD", "Password123!")
INVALID_PASSWORD = os.environ.get("LOGIN_INVALID_PASSWORD", "WrongPassword123!")
UNKNOWN_EMAIL = os.environ.get("LOGIN_UNKNOWN_EMAIL", "unknown.user@example.com")
LONG_STRING = os.environ.get("LOGIN_LONG_STRING", "a" * 5000)
RESPONSE_TIME_LIMIT_MS = 3000


class LoginSuccessResponse(TypedDict, total=False):
    token: str
    expires_in: int


class ErrorResponse(TypedDict, total=False):
    detail: str
    error: str
    message: str
    token: str
    expires_in: int


class ValidationTestCase(TypedDict):
    label: str
    body: dict[str, object] | None
    headers: dict[str, str] | None


MALFORMED_JSON_BODY = "{\"email\": \"not-closed"
PLAINTEXT_BODY = "email=valid.user@example.com&password=Password123!"

INVALID_CREDENTIALS_CASES: list[tuple[str, dict[str, object]]] = [
    ("incorrect_password", {"email": VALID_EMAIL, "password": INVALID_PASSWORD}),
    ("unknown_email", {"email": UNKNOWN_EMAIL, "password": VALID_PASSWORD}),
]

MISSING_FIELD_CASES: list[ValidationTestCase] = [
    {"label": "missing_email", "body": {"password": VALID_PASSWORD}, "headers": None},
    {"label": "missing_password", "body": {"email": VALID_EMAIL}, "headers": None},
    {"label": "empty_body", "body": {}, "headers": None},
]

INVALID_INPUT_CASES: list[ValidationTestCase] = [
    {"label": "invalid_email_format", "body": {"email": "not-an-email", "password": VALID_PASSWORD}, "headers": None},
    {"label": "whitespace_only_email", "body": {"email": "   ", "password": VALID_PASSWORD}, "headers": None},
    {"label": "short_password", "body": {"email": VALID_EMAIL, "password": "short"}, "headers": None},
    {"label": "whitespace_only_password", "body": {"email": VALID_EMAIL, "password": "   "}, "headers": None},
    {"label": "extra_unexpected_field", "body": {"email": VALID_EMAIL, "password": VALID_PASSWORD, "unexpected": "field"}, "headers": None},
    {"label": "leading_trailing_whitespace_email", "body": {"email": f"  {VALID_EMAIL}  ", "password": VALID_PASSWORD}, "headers": None},
    {"label": "leading_trailing_whitespace_password", "body": {"email": VALID_EMAIL, "password": f"  {VALID_PASSWORD}  "}, "headers": None},
    {"label": "sql_injection_email", "body": {"email": "' OR 1=1 --", "password": VALID_PASSWORD}, "headers": None},
    {"label": "sql_injection_password", "body": {"email": VALID_EMAIL, "password": "' OR 1=1 --"}, "headers": None},
    {"label": "script_injection_email", "body": {"email": "<script>alert(1)</script>", "password": VALID_PASSWORD}, "headers": None},
    {"label": "script_injection_password", "body": {"email": VALID_EMAIL, "password": "<script>alert(1)</script>"}, "headers": None},
    {"label": "very_long_email", "body": {"email": f"{LONG_STRING}@example.com", "password": VALID_PASSWORD}, "headers": None},
    {"label": "very_long_password", "body": {"email": VALID_EMAIL, "password": LONG_STRING}, "headers": None},
]

INVALID_JSON_CASES: list[tuple[str, object, dict[str, str]]] = [
    ("malformed_json", MALFORMED_JSON_BODY, {"Content-Type": "application/json"}),
    ("non_json_body_with_json_content_type", PLAINTEXT_BODY, {"Content-Type": "application/json"}),
    ("wrong_content_type_text_plain", PLAINTEXT_BODY, {"Content-Type": "text/plain"}),
]


def send_login_request(
    request: APIRequestContext,
    body: dict[str, object] | str | None,
    headers: dict[str, str] | None = None,
) -> APIResponse:
    request_headers: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    if isinstance(body, str):
        return request.post("/api/login", data=body, headers=request_headers)
    return request.post("/api/login", data=json.dumps(body) if body is not None else None, headers=request_headers)


def parse_json_body(response: APIResponse) -> dict:
    try:
        parsed = response.json()
    except Exception as exc:
        pytest.fail(f"Response was not valid JSON: {exc}")
    assert isinstance(parsed, dict), f"Expected JSON object, got {type(parsed).__name__}"
    return parsed


def assert_valid_login_response(body: dict) -> None:
    assert "token" in body, "Expected token in response body"
    assert isinstance(body["token"], str), "Expected token to be a string"
    assert body["token"], "Expected token to be non-empty"
    if "expires_in" in body:
        assert isinstance(body["expires_in"], int), "Expected expires_in to be an integer"
        assert body["expires_in"] > 0, "Expected expires_in to be positive"
    for sensitive_key in ("password", "pass", "secret"):
        assert sensitive_key not in body, f"Response must not expose sensitive field: {sensitive_key}"


def assert_validation_error(response: APIResponse, label: str) -> None:
    assert response.status in (400, 422), f"{label}: expected 400 or 422, got {response.status}"
    assert response.headers.get("content-type", "").startswith("application/json"), (
        f"{label}: expected JSON content type, got {response.headers.get('content-type', '')}"
    )
    body = parse_json_body(response)
    assert body, f"{label}: expected non-empty error response body"


class TestHappyPath:
    def test_returns_200_and_token_for_valid_credentials(self, request: APIRequestContext) -> None:
        response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        assert response.status == 200
        assert response.headers.get("content-type", "").startswith("application/json")
        body = parse_json_body(response)
        assert_valid_login_response(body)

    def test_returns_unique_tokens_across_successful_logins(self, request: APIRequestContext) -> None:
        first_response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        second_response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        assert first_response.status == 200
        assert second_response.status == 200
        first_body = parse_json_body(first_response)
        second_body = parse_json_body(second_response)
        assert_valid_login_response(first_body)
        assert_valid_login_response(second_body)
        assert first_body["token"] != second_body["token"], "Expected unique tokens per successful login"


class TestAuthentication:
    @pytest.mark.parametrize("label,payload", INVALID_CREDENTIALS_CASES)
    def test_returns_401_for_invalid_credentials(self, request: APIRequestContext, label: str, payload: dict[str, object]) -> None:
        response = send_login_request(request, payload)
        assert response.status == 401, f"{label}: expected 401, got {response.status}"
        assert response.headers.get("content-type", "").startswith("application/json")
        body = parse_json_body(response)
        assert "token" not in body
        body_text = json.dumps(body).lower()
        assert "password" not in body_text or "incorrect" not in body_text
        assert "email" not in body_text or "incorrect" not in body_text

    def test_login_is_accessible_without_prior_session(self, request: APIRequestContext) -> None:
        response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        assert response.status == 200

    def test_authenticated_requests_do_not_break_login_behavior(self, request: APIRequestContext) -> None:
        response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        assert response.status == 200
        body = parse_json_body(response)
        assert_valid_login_response(body)

    def test_password_is_not_echoed_back_in_success_response(self, request: APIRequestContext) -> None:
        response = send_login_request(request, {"email": VALID_EMAIL, "password": VALID_PASSWORD})
        assert response.status == 200
        body_text = response.text()
        assert VALID_PASSWORD not in body_text


class TestValidationMissingFields:
    @pytest.mark.parametrize("case", MISSING_FIELD_CASES)
    def test_returns_validation_error_for_missing_fields(self, request: APIRequestContext, case: ValidationTestCase) -> None:
        response = send_login_request(request, case["body"], case["headers"])
        assert_validation_error(response, case["label"])

    @pytest.mark.parametrize("case", INVALID_INPUT_CASES)
    def test_returns_validation_error_for_invalid_inputs(self, request: APIRequestContext, case: ValidationTestCase) -> None:
        response = send_login_request(request, case["body"], case["headers"])
        assert_validation_error(response, case["label"])

    @pytest.mark.parametrize("label,body,headers", INVALID_JSON_CASES)
    def test_returns_error_for_malformed_or_non_json_payloads(
        self,
        request: APIRequestContext,
        label: str,
        body: object,
        headers: dict[str, str],
    ) -> None:
        response = request.post("/api/login", data=body, headers=headers)
        assert response.status in (400, 422), f"{label}: expected 400 or 422, got {response.status}"
        assert response.headers.get("content-type", "").startswith("application/json"), (
            f"{label}: expected JSON content type, got {response.headers.get('content-type', '')}"
        )

    def test_rate_limiting_or_bruteforce_protection_if_implemented(self, request: APIRequestContext) -> None:
        response = send_login_request(request, {"email": VALID_EMAIL, "password": INVALID_PASSWORD})
        assert response.status in (401, 429), f"expected 401 or 429, got {response.status}"
