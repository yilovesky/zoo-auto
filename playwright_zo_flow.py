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
from login_zo import fetch_magic_link_from_gmail, trigger_login_email

SUCCESS_SCREENSHOT_PATH = Path("zo_workspace_reply.png")
FAIL_SCREENSHOT_PATH = Path("zo_failure_state.png")
STATE_PATH = Path("zo_storage_state.json")
PROMPT = os.getenv(
    "ZO_PROMPT",
    """你先帮我重启我的哪吒探针agent.sh，确保哪吒探针agent.sh在运行后再帮我依次运行下面的代码，并发给我日志中显示的最新的域名

nohup /usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8000 >> /opt/openai-cpa/cf.log 2>&1 &

cd /opt/openai-cpa && source venv/bin/activate

nohup python wfxl_openai_regst.py >> /opt/openai-cpa/run.log 2>&1 &

grep -o 'https://.*\.trycloudflare\.com' /opt/openai-cpa/cf.log""",
)


def extract_latest_trycloudflare_domain(text: str):
    import re

    matches = re.findall(r"https://[^\s'\"]+\.trycloudflare\.com", text)
    return matches[-1] if matches else None


def build_success_caption(body: str) -> str:
    domain = extract_latest_trycloudflare_domain(body)
    if domain:
        return f"最新域名: {domain}"
    return "Zo 自动流程成功截图"


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
    urls = ["https://app.zo.computer/", "https://baico.zo.computer/", "https://www.zo.computer/app", "https://www.zo.computer/"]
    input_selector = "div[contenteditable='true']"
    workspace_markers = [
        "新聊天", "首页", "文件", "聊天", "空间", "回复...", "有什么我能帮你的？", "New chat", "Recent chats",
        "Home", "Files", "Chats", "Automations", "Skills", "Settings", "TODAY", "YESTERDAY", "Channels", "Integrations",
    ]
    marketing_markers = ["Sign up", "YOUR COMPUTER IN THE CLOUD", "PEOPLE LOVE ZO", "Customer Testimonials"]
    marketing_only_markers = ["Pricing", "Blog", "Your home on the Internet", "Always-on AI that remembers you"]
    strong_workspace_markers = ["Home", "Files", "Chats", "Automations", "Skills", "Settings", "TODAY", "YESTERDAY", "Channels", "Integrations"]
    for url in urls:
        print(f"正在尝试访问并校验状态: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass

            body_text = await page.locator("body").inner_text()

            editor_found = False
            if hasattr(page, 'query_selector'):
                editor_element = await page.query_selector(input_selector)
                editor_found = (editor_element is not None)
            else:
                editor_found = any(x in body_text for x in ["回复...", "有什么我能帮你的？"])
                if not editor_found:
                    editor_found = any(x in body_text for x in ["新聊天", "New chat"])

            has_markers = any(x in body_text for x in workspace_markers)
            strong_workspace_count = sum(1 for x in strong_workspace_markers if x in body_text)
            has_recent_or_integrations = any(x in body_text for x in ["Recent chats", "TODAY", "YESTERDAY", "Channels", "Integrations"])
            looks_like_marketing_only = (
                any(m in body_text for m in marketing_markers)
                and not editor_found
                and not has_recent_or_integrations
                and any(m in body_text for m in marketing_only_markers)
            )
            if looks_like_marketing_only:
                continue

            if has_markers and (editor_found or has_recent_or_integrations):
                print(f"✅ 状态校验通过")
                return True
            else:
                print(f"⚠️ 未发现完整工作区特征")

        except Exception as e:
            print(f"访问 {url} 遇到预期外的错误: {str(e)}")
            continue

    return False


async def fill_prosemirror(editor, page, text):
    await editor.click(force=True)
    try:
        await editor.fill(text)
    except Exception:
        pass
    current_text = (await editor.inner_text()).strip()
    if current_text != text:
        try:
            await page.keyboard.press("Control+A")
        except Exception:
            pass
        try:
            await page.keyboard.press("Meta+A")
        except Exception:
            pass
        await page.keyboard.type(text)
    await page.wait_for_timeout(1000)


async def click_send_button_if_present(page) -> bool:
    selectors = [
        "button[type='submit']",
        "button[aria-label='Send message']",
        "button[aria-label='发送']",
        "button[data-testid='send-button']",
        "button:has(svg)",
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).last
            await button.wait_for(timeout=3000)
            await button.click(force=True)
            return True
        except Exception:
            continue
    return False


def body_shows_submitted_state(body_before: str, body_after: str) -> bool:
    if PROMPT in body_after and "Zo is thinking" not in body_after and "Press Esc to stop" not in body_after and len(body_after) > len(body_before):
        return True

    if extract_latest_trycloudflare_domain(body_after):
        return True

    transition_markers = ["回复...", "加载中...", "Thinking...", "Zo is thinking", "Press Esc to stop"]
    stable_markers = ["最终回复内容", "最新域名"]
    if any(marker in body_after for marker in transition_markers):
        before_has_reply_markers = any(marker in body_before for marker in transition_markers)
        after_has_reply_state = any(marker in body_after for marker in stable_markers)
        if after_has_reply_state and not before_has_reply_markers:
            return True

    return False


async def try_send_prompt(page):
    body_before = await page.locator("body").inner_text()
    selector_candidates = [
        "div[contenteditable='true'][data-placeholder='有什么我能帮你的？']",
        "div[contenteditable='true'][data-placeholder='回复...']",
        "div.tiptap.ProseMirror",
        "div[contenteditable='true']",
    ]
    editor = None
    selector = None
    for candidate in selector_candidates:
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
    body_after_enter = await page.locator("body").inner_text()
    if PROMPT not in body_after_enter:
        clicked = await click_send_button_if_present(page)
        if clicked:
            await page.wait_for_timeout(1000)
    await page.wait_for_timeout(3000)
    last_body = await page.locator("body").inner_text()
    if body_shows_submitted_state(body_before, last_body):
        return True, last_body
    deadline = time.time() + 180
    while time.time() < deadline:
        await page.wait_for_timeout(3000)
        last_body = await page.locator("body").inner_text()
        if body_shows_submitted_state(body_before, last_body):
            return True, last_body
    return False, last_body


async def fill_prompt_and_wait(page):
    return await try_send_prompt(page)


async def ensure_logged_in(page, email_addr: str) -> bool:
    if await wait_for_workspace(page):
        return True
    if choose_auth_strategy() == "saved_state":
        try:
            await page.context.clear_cookies()
        except Exception:
            pass
    trigger_login_email(email_addr)
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if app_password:
        try:
            link = fetch_magic_link_from_gmail(email_addr, app_password, timeout_seconds=120)
            await page.goto(link, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
        except Exception:
            pass
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
            tg_send_photo(SUCCESS_SCREENSHOT_PATH, build_success_caption(body))
            print(f"Screenshot saved to {SUCCESS_SCREENSHOT_PATH.resolve()}")
        else:
            await page.screenshot(path=str(FAIL_SCREENSHOT_PATH), full_page=True)
            tg_send_photo(FAIL_SCREENSHOT_PATH, "Zo 自动流程失败截图")
            print(f"Failure screenshot saved to {FAIL_SCREENSHOT_PATH.resolve()}")
            print(body[:4000])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_flow())
