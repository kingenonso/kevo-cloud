"""
Tests for kyc_client.py (Batch B, group 5 item 21, 2026-10-22).

None of these tests make a real network call to Sumsub - every requests
call is mocked, same discipline as test_email_client.py mocking Mailgun
and test_m26e_escrow_integration.py mocking Escrow.com. Real sandbox
verification (once Eze has a real Sumsub sandbox account) is done
separately, live.
"""
import pytest
from unittest.mock import patch, MagicMock

import kyc_client


def _unset_kyc_env(monkeypatch):
    monkeypatch.delenv("SUMSUB_APP_TOKEN", raising=False)
    monkeypatch.delenv("SUMSUB_SECRET_KEY", raising=False)


def _set_kyc_env(monkeypatch):
    _unset_kyc_env(monkeypatch)
    monkeypatch.setenv("SUMSUB_APP_TOKEN", "test-app-token")
    monkeypatch.setenv("SUMSUB_SECRET_KEY", "test-secret-key")


def _mock_response(ok=True, json_value=None, status_code=200, text=""):
    mock_response = MagicMock()
    mock_response.ok = ok
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json.return_value = json_value if json_value is not None else {}
    return mock_response


# --- Not configured ---

def test_create_applicant_raises_when_not_configured(monkeypatch):
    _unset_kyc_env(monkeypatch)
    with pytest.raises(RuntimeError, match="SUMSUB_APP_TOKEN and SUMSUB_SECRET_KEY"):
        kyc_client.create_applicant("42")


def test_get_applicant_status_raises_when_not_configured(monkeypatch):
    _unset_kyc_env(monkeypatch)
    with pytest.raises(RuntimeError, match="SUMSUB_APP_TOKEN and SUMSUB_SECRET_KEY"):
        kyc_client.get_applicant_status("applicant-1")


def test_get_applicant_review_result_raises_when_not_configured(monkeypatch):
    _unset_kyc_env(monkeypatch)
    with pytest.raises(RuntimeError, match="SUMSUB_APP_TOKEN and SUMSUB_SECRET_KEY"):
        kyc_client.get_applicant_review_result("applicant-1")


def test_generate_access_token_raises_when_not_configured(monkeypatch):
    _unset_kyc_env(monkeypatch)
    with pytest.raises(RuntimeError, match="SUMSUB_APP_TOKEN and SUMSUB_SECRET_KEY"):
        kyc_client.generate_access_token("42")


# --- create_applicant ---

def test_create_applicant_success(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"id": "applicant-123", "externalUserId": "42"})

    with patch("kyc_client.requests.post", return_value=mock_response) as mock_post:
        result = kyc_client.create_applicant(
            "42", email="buyer@example.com", first_name="Ada", last_name="Lovelace"
        )

    assert result == {"id": "applicant-123", "externalUserId": "42"}
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "https://api.sumsub.com/resources/applicants?levelName=basic-kyc-level"
    headers = call_args.kwargs["headers"]
    assert headers["X-App-Token"] == "test-app-token"
    assert "X-App-Access-Sig" in headers
    assert "X-App-Access-Ts" in headers
    import json
    body = json.loads(call_args.kwargs["data"])
    assert body["externalUserId"] == "42"
    assert body["email"] == "buyer@example.com"
    assert body["info"] == {"firstName": "Ada", "lastName": "Lovelace"}


def test_create_applicant_minimal_fields(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"id": "applicant-456"})

    with patch("kyc_client.requests.post", return_value=mock_response) as mock_post:
        kyc_client.create_applicant("99")

    import json
    body = json.loads(mock_post.call_args.kwargs["data"])
    assert body == {"externalUserId": "99"}


def test_create_applicant_raises_on_api_error(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(ok=False, status_code=401, text="Invalid signature")

    with patch("kyc_client.requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Sumsub API error 401"):
            kyc_client.create_applicant("42")


def test_create_applicant_custom_level_name(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"id": "applicant-789"})

    with patch("kyc_client.requests.post", return_value=mock_response) as mock_post:
        kyc_client.create_applicant("42", level_name="enhanced-kyc-level")

    assert "levelName=enhanced-kyc-level" in mock_post.call_args.args[0]


# --- get_applicant_status ---

def test_get_applicant_status_success(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"reviewStatus": "pending"})

    with patch("kyc_client.requests.get", return_value=mock_response) as mock_get:
        result = kyc_client.get_applicant_status("applicant-123")

    assert result == {"reviewStatus": "pending"}
    assert mock_get.call_args.args[0] == "https://api.sumsub.com/resources/applicants/applicant-123/status"


def test_get_applicant_status_raises_on_api_error(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(ok=False, status_code=404, text="Applicant not found")

    with patch("kyc_client.requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Sumsub API error 404"):
            kyc_client.get_applicant_status("nonexistent")


# --- get_applicant_review_result ---

def test_get_applicant_review_result_success(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={
        "id": "applicant-123",
        "review": {"reviewResult": {"reviewAnswer": "GREEN"}},
    })

    with patch("kyc_client.requests.get", return_value=mock_response) as mock_get:
        result = kyc_client.get_applicant_review_result("applicant-123")

    assert result["review"]["reviewResult"]["reviewAnswer"] == "GREEN"
    assert mock_get.call_args.args[0] == "https://api.sumsub.com/resources/applicants/applicant-123/one"


# --- generate_access_token ---

def test_generate_access_token_success(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"token": "act-xyz", "userId": "42"})

    with patch("kyc_client.requests.post", return_value=mock_response) as mock_post:
        result = kyc_client.generate_access_token("42")

    assert result == {"token": "act-xyz", "userId": "42"}
    assert "userId=42" in mock_post.call_args.args[0]
    assert "levelName=basic-kyc-level" in mock_post.call_args.args[0]


# --- Request signing ---

def test_signature_changes_with_body(monkeypatch):
    _set_kyc_env(monkeypatch)
    mock_response = _mock_response(json_value={"id": "a1"})

    sigs = []
    with patch("kyc_client.requests.post", return_value=mock_response) as mock_post:
        kyc_client.create_applicant("1")
        sigs.append(mock_post.call_args.kwargs["headers"]["X-App-Access-Sig"])
        kyc_client.create_applicant("2")
        sigs.append(mock_post.call_args.kwargs["headers"]["X-App-Access-Sig"])

    assert sigs[0] != sigs[1]
