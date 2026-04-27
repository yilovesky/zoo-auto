from email.message import EmailMessage

import pytest

from login_zo import extract_magic_link, find_latest_zo_magic_link, trigger_login_email



def make_dated_message(subject: str, body: str, date_header: str, sender: str = "Zo <hello@zo.computer>") -> EmailMessage:
    msg = make_message(subject, body, sender=sender)
    msg["Date"] = date_header
    return msg


def make_message(subject: str, body: str, sender: str = "Zo <hello@zo.computer>") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "yilovesky520@gmail.com"
    msg.set_content(body)
    return msg


def test_extract_magic_link_prefers_verify_url():
    body = (
        "Click here: https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=abc123\n"
        "Other link: https://www.zo.computer/pricing\n"
    )
    assert (
        extract_magic_link(body)
        == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=abc123"
    )


def test_extract_magic_link_supports_redirect_wrapped_url():
    body = (
        "Wrapped: https://c.vialoops.com/CL0/https:%2F%2Fwww.zo.computer%2Fapi%2Femail-login%2Fverify%3Fredirect%3D%252Fsignup%26token%3Dxyz/1/test"
    )
    assert (
        extract_magic_link(body)
        == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=xyz"
    )


def test_find_latest_zo_magic_link_ignores_non_zo_messages():
    messages = [
        make_message("Welcome", "https://example.com"),
        make_message(
            "Your Zo login link",
            "Use https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=***"
        ),
    ]
    assert (
        find_latest_zo_magic_link(messages)
        == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=***"
    )


def test_extract_magic_link_reassembles_quoted_printable_soft_breaks():
    body = (
        "Use this link to log in to Zo Computer:\n\n"
        "https://www.zo.computer/api/email-login/verify?redirect=3D%2Fsignup&token=3D"
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjEyMzQ1fQ.=\n"
        "abc123xyz\n\n"
        "If the button in this email doesn’t work, you can copy and paste the link above into your browser.\n"
    )
    assert (
        extract_magic_link(body)
        == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjEyMzQ1fQ.abc123xyz"
    )


def test_find_latest_zo_magic_link_prefers_newest_message_date():
    older = make_dated_message(
        "Your Zo login link",
        "Use https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=old-token",
        "Mon, 01 Jan 2024 10:00:00 +0000",
    )
    newer = make_dated_message(
        "Your Zo login link",
        "Use https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=new-token",
        "Mon, 01 Jan 2024 10:05:00 +0000",
    )
    assert find_latest_zo_magic_link([newer, older]) == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=new-token"


def test_trigger_login_email_uses_current_request_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class DummyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(req, context=None, timeout=0):
        captured['full_url'] = req.full_url
        captured['method'] = req.get_method()
        captured['data'] = req.data
        captured['headers'] = dict(req.header_items())
        return DummyResponse()

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)

    trigger_login_email('user@example.com')

    assert captured['full_url'] == 'https://www.zo.computer/api/email-login/request'
    assert captured['method'] == 'POST'
    assert captured['data'] == b'{"email": "user@example.com", "redirect": "/signup"}'
    assert captured['headers']['Content-type'] == 'application/json'
