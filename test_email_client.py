"""
Tests for email_client.py (Batch B, group 1 item 2, 2026-09-21).

None of these tests make a real network call to Mailgun - every
requests.post call is mocked, same discipline as
test_m26e_escrow_integration.py mocking escrow_client. Real sandbox
verification (once Eze has a real Mailgun sandbox account) is done
separately, live.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

import email_client


def _unset_email_env(monkeypatch):
    monkeypatch.delenv("EMAIL_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)


def test_send_email_raises_when_not_configured(monkeypatch):
    _unset_email_env(monkeypatch)
    with pytest.raises(RuntimeError, match="EMAIL_API_KEY and EMAIL_DOMAIN"):
        email_client.send_email("someone@example.com", "Subject", "Body")


def test_send_email_success(monkeypatch):
    _unset_email_env(monkeypatch)
    monkeypatch.setenv("EMAIL_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_DOMAIN", "sandbox123.mailgun.org")

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"id": "<mock-id@mailgun>", "message": "Queued"}

    with patch("email_client.requests.post", return_value=mock_response) as mock_post:
        result = email_client.send_email(
            "recipient@example.com", "Reset your password", "Click here: ..."
        )

    assert result == {"id": "<mock-id@mailgun>", "message": "Queued"}
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "https://api.mailgun.net/v3/sandbox123.mailgun.org/messages"
    assert call_args.kwargs["auth"] == ("api", "test-key")
    assert call_args.kwargs["data"]["to"] == ["recipient@example.com"]
    assert call_args.kwargs["data"]["subject"] == "Reset your password"
    assert call_args.kwargs["data"]["text"] == "Click here: ..."
    assert "KEVO" in call_args.kwargs["data"]["from"]


def test_send_email_raises_on_api_error(monkeypatch):
    _unset_email_env(monkeypatch)
    monkeypatch.setenv("EMAIL_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_DOMAIN", "sandbox123.mailgun.org")

    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 401
    mock_response.text = "Forbidden"

    with patch("email_client.requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Mailgun API error 401"):
            email_client.send_email("recipient@example.com", "Subject", "Body")


def test_send_email_uses_custom_from_address(monkeypatch):
    _unset_email_env(monkeypatch)
    monkeypatch.setenv("EMAIL_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_DOMAIN", "sandbox123.mailgun.org")
    monkeypatch.setenv("EMAIL_FROM", "KEVO Support <support@kevo.example>")

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {}

    with patch("email_client.requests.post", return_value=mock_response) as mock_post:
        email_client.send_email("recipient@example.com", "Subject", "Body")

    assert mock_post.call_args.kwargs["data"]["from"] == "KEVO Support <support@kevo.example>"
