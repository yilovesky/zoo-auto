#!/usr/bin/env python3
import asyncio
import email
import imaplib
import os
import time
import urllib.request
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from login_zo import trigger_login_email, find_latest_zo_magic_link

SUCCESS_SCREENSHOT_PATH = Path("zo_workspace_reply.png")
FAIL_SCREENSHOT_PATH = Path("zo_failure_state.png")
HTML_DUMP_PATH = Path("zo_workspace_debug.html")
STATE_PATH = Path("zo_storage_state.json")
LINK_PATH = Path("latest_zo_link.txt")
PROMPT = "现在北京时间是几点"


def load_dotenv(path: str = "/root/zoo-auto/.env"):
    if not os.path.exists(path):
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k, v)


def tg_send_photo(photo_path: Path, caption: str) -> None:
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id or not photo_path.exists():
        return
    boundary = "----HermesBoundary7MA4YWxkTrZu0gW"
    parts = []
    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("chat_id", chat_id)
    field("caption", caption)
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{photo_path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode() + photo_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()


def is_storage_state_file_usable(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return False
    return any(
        isinstance(cookie, dict)
        and cookie.get("name")
        and cookie.get("value")
        and "zo.computer" in str(cookie.get("domain", ""))
        for cookie in cookies
    )


def choose_auth_strategy() -> str:
    return "saved_state" if is_storage_state_file_usable(STATE_PATH) else "magic_link"


async def create_context(browser):
    kwargs = {"viewport": {"width": 1440, "height": 1100}}
    if choose_auth_strategy() == "saved_state":
        kwargs["storage_state"] = str(STATE_PATH)
    return await browser.new_context(**kwargs)


def fetch_magic_link_since(email_address: str, app_password: str, since_ts: float, timeout_seconds: int = 180) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
            mail.login(email_address, app_password)
            mail.select("INBOX")
            status, data = mail.search(None, '(TEXT "zo.computer")')
            ids = [i for i in data[0].split() if i] if status == "OK" and data and data[0] else []
            if ids:
                messages = []
                for msg_id in ids[-15:]:
                    _, parts = mail.fetch(msg_id, "(RFC822)")
                    messages.append(email.message_from_bytes(parts[0][1]))
                from login_zo import _message_timestamp
                candidates = [m for m in messages if _message_timestamp(m) >= since_ts - 5]
                link = find_latest_zo_magic_link(candidates or messages)
                if link:
                    LINK_PATH.write_text(link)
                    return link
        time.sleep(5)
    raise TimeoutError("Timed out waiting for fresh Zo login email")


async def wait_for_workspace(page):
    urls = ["https://baico.zo.computer/", "https://app.zo.computer/", "https://www.zo.computer/app", "https://www.zo.computer/"]
    workspace_markers = ['新聊天', '首页', '文件', '聊天', '空间', '回复...', 'New chat', 'Recent chats']
    marketing_markers = ['Sign up', 'YOUR COMPUTER IN THE CLOUD', 'PEOPLE LOVE ZO', 'Customer Testimonials']
    for url in urls:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        current_url = page.url
        body = await page.locator('body').inner_text()
        is_workspace_host = current_url.startswith("https://app.zo.computer") or current_url.startswith("https://baico.zo.computer")
        if is_workspace_host and any(x in body for x in workspace_markers) and not any(x in body for x in marketing_markers):
            return True
    return False


async def inspect_candidates(page):
    return await page.evaluate(
        """
        () => [...document.querySelectorAll('textarea,input,[contenteditable="true"],button,a')].slice(0,200).map((el, i) => ({
          i,
          tag: el.tagName,
          type: el.getAttribute('type'),
          aria: el.getAttribute('aria-label'),
          role: el.getAttribute('role'),
          href: el.getAttribute('href'),
          placeholder: el.getAttribute('placeholder'),
          editable: el.getAttribute('contenteditable'),
          text: (el.innerText || el.textContent || '').trim().slice(0,160),
          cls: typeof el.className === 'string' ? el.className.slice(0,160) : ''
        }))
        """
    )


async def fill_prosemirror(editor, page, text):
    await editor.click(force=True)
    await editor.evaluate(
        """
        (el, value) => {
          el.focus();
          const p = document.createElement('p');
          p.textContent = value;
          el.innerHTML = '';
          el.appendChild(p);
          el.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, inputType: 'insertText', data: value}));
          el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
        }
        """,
        text,
    )
    await page.wait_for_timeout(1000)


async def try_send_prompt(page):
    body_before = await page.locator('body').inner_text()
    primary_selector = "div[contenteditable='true'][data-placeholder='有什么我能帮你的？']"
    fallback_selector = "div[contenteditable='true'][data-placeholder='回复...']"
    editor_selector = primary_selector
    editor = page.locator(editor_selector).last
    try:
        await editor.wait_for(timeout=30000)
    except PlaywrightTimeoutError:
        editor_selector = fallback_selector
        editor = page.locator(editor_selector).last
        await editor.wait_for(timeout=30000)
    await fill_prosemirror(editor, page, PROMPT)
    await page.press(editor_selector, 'Enter')
    await page.wait_for_timeout(3000)
    deadline = time.time() + 180
    last_body = await page.locator('body').inner_text()
    while time.time() < deadline:
        if PROMPT in last_body and 'Zo is thinking' not in last_body and 'Press Esc to stop' not in last_body and len(last_body) > len(body_before):
            return True, last_body
        await page.wait_for_timeout(3000)
        last_body = await page.locator('body').inner_text()
    return False, last_body


async def ensure_logged_in(page, email_addr: str, app_password: str) -> bool:
    if await wait_for_workspace(page):
        return True

    start_ts = time.time()
    trigger_login_email(email_addr)
    link = fetch_magic_link_since(email_addr, app_password, start_ts, timeout_seconds=180)
    print(f"Magic link: {link}")
    await page.goto('https://www.zo.computer/signup', wait_until='domcontentloaded', timeout=60000)
    try:
        await page.wait_for_load_state('networkidle', timeout=15000)
    except PlaywrightTimeoutError:
        pass
    await page.goto(link, wait_until='domcontentloaded', timeout=60000)
    try:
        await page.wait_for_load_state('networkidle', timeout=30000)
    except PlaywrightTimeoutError:
        pass
    await page.wait_for_timeout(8000)
    return await wait_for_workspace(page)


async def run_flow():
    load_dotenv()
    email_addr = os.getenv("ZO_EMAIL") or os.getenv("GMAIL_USER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not email_addr or not app_password:
        raise SystemExit("ZO_EMAIL/GMAIL_USER and GMAIL_APP_PASSWORD are required")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await create_context(browser)
        page = await context.new_page()
        page.set_default_timeout(45000)
        await page.goto('https://app.zo.computer/', wait_until='domcontentloaded', timeout=60000)
        try:
            await page.wait_for_load_state('networkidle', timeout=15000)
        except PlaywrightTimeoutError:
            pass

        ok = await ensure_logged_in(page, email_addr, app_password)
        sent = False
        body = ''
        if ok:
            try:
                sent, body = await try_send_prompt(page)
            except Exception as e:
                print('send_error', repr(e))
                body = await page.locator('body').inner_text()
        else:
            body = await page.locator('body').inner_text()

        await context.storage_state(path=str(STATE_PATH))
        HTML_DUMP_PATH.write_text(await page.content())
        Path('zo_dom_candidates.json').write_text(json.dumps(await inspect_candidates(page), ensure_ascii=False, indent=2))

        if sent:
            await page.screenshot(path=str(SUCCESS_SCREENSHOT_PATH), full_page=True)
            tg_send_photo(SUCCESS_SCREENSHOT_PATH, 'Zo 自动流程现场截图（已触发发送/等待回复）')
            print(f"Screenshot saved to {SUCCESS_SCREENSHOT_PATH.resolve()}")
        else:
            await page.screenshot(path=str(FAIL_SCREENSHOT_PATH), full_page=True)
            tg_send_photo(FAIL_SCREENSHOT_PATH, 'Zo 自动流程失败现场截图')
            print(f"Failure screenshot saved to {FAIL_SCREENSHOT_PATH.resolve()}")
            print('BODY_SNIPPET_START')
            print(body[:4000])
            print('BODY_SNIPPET_END')

        await browser.close()


if __name__ == '__main__':
    asyncio.run(run_flow())
