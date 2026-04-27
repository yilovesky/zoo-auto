#!/usr/bin/env python3
import argparse
import email
import imaplib
import os
import re
import ssl
import time
import webbrowser
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable, Optional
from urllib.parse import unquote

ZO_VERIFY_RE = re.compile(r'https://www\.zo\.computer/api/email-login/verify\?[^\s<>"\']+', re.IGNORECASE)
GENERIC_URL_RE = re.compile(r'https?://[^\s<>"\']+')


def extract_magic_link(text: str) -> Optional[str]:
    if not text:
        return None
    text = unescape(text)
    direct = ZO_VERIFY_RE.search(text)
    if direct:
        return _clean_url(direct.group(0))
    for candidate in GENERIC_URL_RE.findall(text):
        decoded = unquote(candidate)
        direct = ZO_VERIFY_RE.search(decoded)
        if direct:
            return _clean_url(direct.group(0))
    return None


def find_latest_zo_magic_link(messages: Iterable[Message]) -> Optional[str]:
    latest = None
    latest_ts = None
    for msg in messages:
        link = extract_magic_link(_message_text(msg))
        if not link:
            continue
        ts = _message_timestamp(msg)
        if latest is None or ts >= latest_ts:
            latest = link
            latest_ts = ts
    return latest


def trigger_login_email(address: str) -> None:
    import urllib.request
    import urllib.parse

    payload = urllib.parse.urlencode({"email": address}).encode()
    req = urllib.request.Request(
        "https://www.zo.computer/api/email-login",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "zoo-auto-login-script",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=30) as resp:
        resp.read()


def fetch_magic_link_from_gmail(email_address: str, app_password: str, timeout_seconds: int = 120) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
            mail.login(email_address, app_password)
            mail.select("INBOX")
            _, data = mail.search(None, '(FROM "zo" SUBJECT "login")')
            ids = [i for i in data[0].split() if i]
            if ids:
                messages = []
                for msg_id in ids[-10:]:
                    _, parts = mail.fetch(msg_id, "(RFC822)")
                    raw = parts[0][1]
                    messages.append(email.message_from_bytes(raw))
                link = find_latest_zo_magic_link(messages)
                if link:
                    return link
        time.sleep(5)
    raise TimeoutError("Timed out waiting for Zo login email")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Zo email login and open the returned magic link.")
    parser.add_argument("--email", default=os.getenv("GMAIL_USER"))
    parser.add_argument("--app-password", default=os.getenv("GMAIL_APP_PASSWORD"))
    parser.add_argument("--no-browser", action="store_true", help="Print the magic link instead of opening it")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    if not args.email or not args.app_password:
        raise SystemExit("GMAIL_USER and GMAIL_APP_PASSWORD are required")

    print("Triggering Zo login email...")
    trigger_login_email(args.email)
    print("Waiting for latest Zo email...")
    link = fetch_magic_link_from_gmail(args.email, args.app_password, timeout_seconds=args.timeout)
    print(f"Magic link: {link}")
    if not args.no_browser:
        webbrowser.open(link)
        print("Opened magic link in default browser.")
    return 0


def _message_text(msg: Message) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(parts)
    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload())
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _message_timestamp(msg: Message) -> float:
    try:
        return parsedate_to_datetime(msg.get("Date")).timestamp()
    except Exception:
        return 0.0


def _clean_url(url: str) -> str:
    url = url.rstrip('>.)]"\'')
    if '/1/' in url and 'token=' in url:
        url = url.split('/1/', 1)[0]
    return url


if __name__ == "__main__":
    raise SystemExit(main())
