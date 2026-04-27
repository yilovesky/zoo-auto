#!/usr/bin/env python3
import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from github_secrets import update_github_storage_secret_if_possible, write_storage_state_if_present
from login_zo import trigger_login_email

SUCCESS_SCREENSHOT_PATH = Path("zo_workspace_reply.png")
FAIL_SCREENSHOT_PATH = Path("zo_failure_state.png")
STATE_PATH = Path("zo_storage_state.json")
PROMPT = os.getenv("ZO_PROMPT", "现在北京时间是几点")


def tg_send_photo(photo_path: Path, caption: str) -> None:
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id or not photo_path.exists():
        return
    boundary = "----HermesBoundary7MA4YWxkTrZu0gW"
    parts = []

    def field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    field("chat_id", chat_id)
    field("caption", caption)
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{photo_path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode()
        + photo_path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()


def load_storage_state_from_env():
    from github_secrets import load_storage_state_from_env as _load

    return _load()


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


def ensure_storage_state_file() -> bool:
    if is_storage_state_file_usable(STATE_PATH):
        return True
    return write_storage_state_if_present(STATE_PATH) and is_storage_state_file_usable(STATE_PATH)


def choose_auth_strategy() -> str:
    return "saved_state" if ensure_storage_state_file() else "magic_link"


async def create_context(browser):
    kwargs = {"viewport": {"width": 1440, "height": 1100}}
    if choose_auth_strategy() == "saved_state":
        kwargs["storage_state"] = str(STATE_PATH)
    return await browser.new_context(**kwargs)


def serialize_storage_state_for_github_secret(path: Path) -> str:
    from github_secrets import serialize_storage_state_for_github_secret as _serialize

    return _serialize(path)


def build_github_secret_update_payload(secret_value: str) -> dict:
    from github_secrets import build_github_secret_update_payload as _build

    return _build(secret_value)


async def wait_for_workspace(page):
    urls = ["https://app.zo.computer/", "https://baico.zo.computer/", "https://www.zo.computer/app"]
    input_selector = "div[contenteditable='true']"
    
    workspace_markers = ["新聊天", "首页", "文件", "聊天", "空间", "回复...", "New chat", "Recent chats"]
    marketing_markers = ["Sign up", "YOUR COMPUTER IN THE CLOUD", "PEOPLE LOVE ZO"]

    for url in urls:
        print(f"正在尝试访问并校验状态: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            body_text = await page.locator("body").inner_text()
            if any(m in body_text for m in marketing_markers):
                print(f"检测到营销页面内容，判定为未登录。")
                continue
            editor_found = await page.locator(input_selector).count()
            has_markers = any(x in body_text for x in workspace_markers)
            
            if has_markers and editor_found > 0:
                print(f"✅ 状态校验通过：已发现侧边栏和输入框。")
                return True
            else:
                print(f"⚠️ 页面虽有部分特征但未发现输入框 (Editor count: {editor_found})，视为未登录。")
                
        except Exception as e:
            print(f"访问 {url} 出错: {str(e)}")
            continue

    return False


async def fill_prosemirror(editor, page, text):
    await editor.click(force=True)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Control+A")
    await page.wait_for_timeout(200)
    await page.keyboard.press("Backspace")
    await page.wait_for_timeout(500)
    await page.keyboard.type(text, delay=100) 
    await page.wait_for_timeout(1000)


async def try_send_prompt(page):
    body_before = await page.locator("body").inner_text()
    selectors = [
        "div[contenteditable='true'][data-placeholder='有什么我能帮你的？']",
        "div[contenteditable='true'][data-placeholder='回复...']",
    ]
    editor = None
    selector = None
    for candidate in selectors:
        loc = page.locator(candidate).last
        try:
            await loc.wait_for(timeout=15000)
            editor = loc
            selector = candidate
            break
        except PlaywrightTimeoutError:
            continue
    if editor is None or selector is None:
        return False, await page.locator("body").inner_text()
    await fill_prosemirror(editor, page, PROMPT)
    await page.press(selector, "Enter")
    await page.wait_for_timeout(3000)
    deadline = time.time() + 180
    last_body = await page.locator("body").inner_text()
    while time.time() < deadline:
        if PROMPT in last_body and "Zo is thinking" not in last_body and "Press Esc to stop" not in last_body and len(last_body) > len(body_before):
            return True, last_body
        await page.wait_for_timeout(3000)
        last_body = await page.locator("body").inner_text()
    return False, last_body


async def fill_prompt_and_wait(page):
    return await try_send_prompt(page)


async def ensure_logged_in(page, email_addr: str) -> bool:
    if await wait_for_workspace(page):
        return True
    trigger_login_email(email_addr)
    return await wait_for_workspace(page)


async def run_flow():
    email_addr = os.getenv("ZO_EMAIL") or os.getenv("GMAIL_USER")
    if not email_addr:
        raise SystemExit("ZO_EMAIL or GMAIL_USER is required")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await create_context(browser)
        page = await context.new_page()
        page.set_default_timeout(45000)
        await page.goto("https://app.zo.computer/", wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        ok = await ensure_logged_in(page, email_addr)
        sent = False
        body = ""
        if ok:
            sent, body = await fill_prompt_and_wait(page)
        else:
            body = await page.locator("body").inner_text()

        await context.storage_state(path=str(STATE_PATH))
        update_github_storage_secret_if_possible(STATE_PATH)

        if sent:
            await page.screenshot(path=str(SUCCESS_SCREENSHOT_PATH), full_page=True)
            tg_send_photo(SUCCESS_SCREENSHOT_PATH, "Zo 自动流程成功截图")
            print(f"Screenshot saved to {SUCCESS_SCREENSHOT_PATH.resolve()}")
        else:
            await page.screenshot(path=str(FAIL_SCREENSHOT_PATH), full_page=True)
            tg_send_photo(FAIL_SCREENSHOT_PATH, "Zo 自动流程失败截图")
            print(f"Failure screenshot saved to {FAIL_SCREENSHOT_PATH.resolve()}")
            print(body[:4000])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_flow())
