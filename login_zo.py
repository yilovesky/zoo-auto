#!/usr/bin/env python3
import argparse
import email
import imaplib
import json
import os
import quopri
import re
import ssl
import time
import webbrowser
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable, Optional
from urllib.parse import unquote
import urllib.request

ZO_VERIFY_RE = re.compile(r'https://www\.zo\.computer/api/email-login/verify\?[^\s<>"\']+', re.IGNORECASE)
GENERIC_URL_RE = re.compile(r'https?://[^\s<>"\']+')
TOKEN_CONTINUATION_RE = re.compile(
    r'(https://www\.zo\.computer/api/email-login/verify\?[^\s<>"\']*token=)(?:3D)?([A-Za-z0-9._\-]+)(=?)\r?\n([A-Za-z0-9._\-=]+)',
    re.IGNORECASE,
)


def extract_magic_link(text: str) -> Optional[str]:
    if not text:
        return None
    best = None
    for candidate_text in _candidate_texts(text):
        direct = ZO_VERIFY_RE.search(candidate_text)
        if direct:
            candidate_url = _clean_url(direct.group(0))
            if _looks_complete_magic_link(candidate_url):
                return candidate_url
            best = best or candidate_url
        for candidate in GENERIC_URL_RE.findall(candidate_text):
            decoded = unquote(candidate)
            direct = ZO_VERIFY_RE.search(decoded)
            if direct:
                candidate_url = _clean_url(direct.group(0))
                if _looks_complete_magic_link(candidate_url):
                    return candidate_url
                best = best or candidate_url
    return best


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
    payload = json.dumps({"email": address, "redirect": "/signup"}).encode("utf-8")
    req = urllib.request.Request(
        "https://www.zo.computer/api/email-login/request",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "zoo-auto-login-script",
            "Referer": "https://www.zo.computer/signup",
            "Origin": "https://www.zo.computer",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=30) as resp:
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"Zo login trigger failed with HTTP {resp.status}")
        parsed = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        if parsed.get("ok") is not True:
            raise RuntimeError(f"Zo login trigger did not confirm success: {parsed!r}")


def fetch_magic_link_from_gmail(email_address: str, app_password: str, timeout_seconds: int = 120) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
            mail.login(email_address, app_password)
            mail.select("INBOX")
            _, data = mail.search(None, '(OR FROM "zo" FROM "zocomputer")')
            ids = [i for i in data[0].split() if i]
            if not ids:
                _, data = mail.search(None, '(TEXT "zo.computer")')
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


def _candidate_texts(text: str) -> list[str]:
    variants = []
    seen = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    base = unescape(text)
    add(base)
    add(_join_token_continuations(base))
    add(base.replace("=\r\n", "").replace("=\n", ""))

    try:
        decoded = quopri.decodestring(text).decode("utf-8", errors="replace")
    except Exception:
        decoded = ""
    if decoded:
        add(decoded)
        add(_join_token_continuations(decoded))
        add(decoded.replace("\r", "").replace("\n", ""))

    return variants


def _join_token_continuations(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = TOKEN_CONTINUATION_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(4)}" if m.group(3) == "=" else f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}",
            text,
        )
        text = text.replace("redirect=3D", "redirect=").replace("token=3D", "token=")
    return text


def _looks_complete_magic_link(url: str) -> bool:
    return "redirect=%2Fsignup" in url and "token=" in url and not url.endswith("=")


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
