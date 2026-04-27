from email.message import EmailMessage

from login_zo import extract_magic_link, find_latest_zo_magic_link


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
            "Use https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=realtoken",
        ),
    ]
    assert (
        find_latest_zo_magic_link(messages)
        == "https://www.zo.computer/api/email-login/verify?redirect=%2Fsignup&token=realtoken"
    )
