"""Tests for EmailNotifier (SMTP) — all SMTP calls mocked."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from job_match.notification.digest import DigestData
from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError

_TS = datetime(2026, 10, 2, 9, 0, 0)
_EMPTY = DigestData(strong=(), eligible=(), generated_at=_TS)


def _notifier(port: int = 465) -> EmailNotifier:
    return EmailNotifier(
        host="smtp.example.com",
        port=port,
        user="sender@example.com",
        password="secret",
        recipient="me@example.com",
    )


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------

def test_from_env_ok(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "u@g.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("DIGEST_TO", "me@g.com")
    n = EmailNotifier.from_env()
    assert n._host == "smtp.gmail.com"
    assert n._port == 587
    assert n._recipient == "me@g.com"


def test_from_env_missing_raises(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SmtpConfigError, match="SMTP_HOST"):
        EmailNotifier.from_env()


def test_from_env_default_port_465(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "u@e.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("DIGEST_TO", "me@e.com")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    n = EmailNotifier.from_env()
    assert n._port == 465


# ---------------------------------------------------------------------------
# send — SMTP_SSL (port 465)
# ---------------------------------------------------------------------------

def test_send_ssl_port_uses_smtp_ssl():
    n = _notifier(port=465)
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    ssl_patch = "job_match.notification.email_notifier.smtplib.SMTP_SSL"
    with patch(ssl_patch, return_value=mock_smtp) as ssl_cls:
        result = n.send(_EMPTY)
    ssl_cls.assert_called_once_with("smtp.example.com", 465)
    mock_smtp.login.assert_called_once_with("sender@example.com", "secret")
    mock_smtp.sendmail.assert_called_once()
    assert result is True


def test_send_ssl_correct_recipient():
    n = _notifier(port=465)
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    with patch("job_match.notification.email_notifier.smtplib.SMTP_SSL", return_value=mock_smtp):
        n.send(_EMPTY)
    _, call_args, _ = mock_smtp.sendmail.mock_calls[0]
    assert call_args[1] == ["me@example.com"]


# ---------------------------------------------------------------------------
# send — STARTTLS (port 587)
# ---------------------------------------------------------------------------

def test_send_starttls_port_uses_smtp():
    n = _notifier(port=587)
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    smtp_patch = "job_match.notification.email_notifier.smtplib.SMTP"
    with patch(smtp_patch, return_value=mock_smtp) as smtp_cls:
        result = n.send(_EMPTY)
    smtp_cls.assert_called_once_with("smtp.example.com", 587)
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once()
    assert result is True


# ---------------------------------------------------------------------------
# send — failure
# ---------------------------------------------------------------------------

def test_send_returns_false_on_smtp_error():
    n = _notifier(port=465)
    with patch(
        "job_match.notification.email_notifier.smtplib.SMTP_SSL",
        side_effect=Exception("connection refused"),
    ):
        result = n.send(_EMPTY)
    assert result is False


# ---------------------------------------------------------------------------
# subject line
# ---------------------------------------------------------------------------

def test_send_subject_contains_count():
    n = _notifier(port=465)
    captured: list[bytes] = []

    def _fake_sendmail(sender, recipients, msg_bytes):
        captured.append(msg_bytes)

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.sendmail.side_effect = _fake_sendmail

    with patch("job_match.notification.email_notifier.smtplib.SMTP_SSL", return_value=mock_smtp):
        n.send(_EMPTY)

    assert captured
    assert b"0 new job" in captured[0]


# ---------------------------------------------------------------------------
# NotificationService protocol check
# ---------------------------------------------------------------------------

def test_email_notifier_satisfies_protocol():
    from job_match.notification.service import NotificationService
    assert isinstance(_notifier(), NotificationService)
