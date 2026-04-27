#!/usr/bin/env python3
import argparse
import email
import imaplib
import os
import re
import ssl
import time
import webbrowser
import json
import urllib.request
import urllib.parse
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable, Optional

# 尝试导入 Selenium 用于截图，如果没有安装则跳过截图功能
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# 正则表达式优化：确保匹配截图中的超长链接
ZO_VERIFY_RE = re.compile(r'https://www\.zo\.computer/api/email-login/verify\?[^\s<>"\']+', re.IGNORECASE)

def send_tg_notification(token, chat_id, message, photo_path=None):
    """发送 Telegram 消息和截图"""
    base_url = f"https://api.telegram.org/bot{token}"
    
    # 发送文字
    text_url = f"{base_url}/sendMessage"
    text_data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    urllib.request.urlopen(text_url, data=text_data)

    # 发送照片
    if photo_path and os.path.exists(photo_path):
        from binascii import hexlify
        # 简单的多部分表单上传实现
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        parts = [
            f'--{boundary}',
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}',
            f'--{boundary}',
            f'Content-Disposition: form-data; name="photo"; filename="screenshot.png"',
            'Content-Type: image/png\r\n'
        ]
        with open(photo_path, 'rb') as f:
            image_content = f.read()
        
        body = b'\r\n'.join([p.encode() for p in parts]) + b'\r\n' + image_content + f'\r\n--{boundary}--\r\n'.encode()
        req = urllib.request.Request(f"{base_url}/sendPhoto", data=body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        urllib.request.urlopen(req)

def take_screenshot(url, output_path="login_success.png"):
    """使用 Selenium 访问链接并截图"""
    if not HAS_SELENIUM:
        print("未安装 Selenium，跳过截图步骤。")
        return None
    
    chrome_options = Options()
    chrome_options.add_argument("--headless") # 无头模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    try:
        driver.get(url)
        time.sleep(10) # 等待页面加载和跳转完成
        driver.save_screenshot(output_path)
        return output_path
    finally:
        driver.quit()

def _clean_url(url: str) -> str:
    """仅清洗末尾多余字符，严禁截断 token"""
    return url.strip().rstrip('>.)]"\'')

def extract_magic_link(text: str) -> Optional[str]:
    if not text: return None
    text = unescape(text)
    direct = ZO_VERIFY_RE.search(text)
    if direct:
        return _clean_url(direct.group(0))
    return None

def trigger_login_email(address: str) -> None:
    # 截图显示 POST 数据可能是 JSON 格式，这里改为更通用的处理
    data = json.dumps({"email": address}).encode('utf-8')
    req = urllib.request.Request(
        "https://www.zo.computer/api/email-login",
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=30) as resp:
        return resp.read()

def fetch_magic_link_from_gmail(email_address: str, app_password: str, timeout_seconds: int = 120) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
                mail.login(email_address, app_password)
                mail.select("INBOX")
                # 优化搜索条件：发件人和主题与截图保持一致
                status, data = mail.search(None, '(FROM "no-reply@zocomputer.com" SUBJECT "Log in to Zo Computer")')
                ids = data[0].split()
                if ids:
                    _, parts = mail.fetch(ids[-1], "(RFC822)")
                    msg = email.message_from_bytes(parts[0][1])
                    link = extract_magic_link(_message_text(msg))
                    if link:
                        return link
        except Exception as e:
            print(f"IMAP Error: {e}")
        time.sleep(10)
    raise TimeoutError("未能在规定时间内收到登录邮件")

def _message_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8')
    return msg.get_payload(decode=True).decode()

def main() -> int:
    # 从环境变量读取配置
    GMAIL_USER = os.getenv("GMAIL_USER")
    GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
    TG_TOKEN = os.getenv("TG_BOT_TOKEN")
    TG_CHAT_ID = os.getenv("TG_CHAT_ID")

    if not GMAIL_USER or not GMAIL_PASS:
        print("错误: 缺少 Gmail 环境变量配置")
        return 1

    print(f"正在为 {GMAIL_USER} 触发登录邮件...")
    trigger_login_email(GMAIL_USER)
    
    print("等待邮件到达...")
    try:
        link = fetch_magic_link_from_gmail(GMAIL_USER, GMAIL_PASS)
        print(f"成功提取链接: {link}")
        
        # 执行截图
        screenshot_file = None
        if HAS_SELENIUM:
            print("正在生成登录成功截图...")
            screenshot_file = take_screenshot(link)
        
        # TG 通知
        if TG_TOKEN and TG_CHAT_ID:
            msg = f"✅ Zo Computer 自动登录成功！\n用户: {GMAIL_USER}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            send_tg_notification(TG_TOKEN, TG_CHAT_ID, msg, screenshot_file)
            print("Telegram 通知已发送")
            
    except Exception as e:
        error_msg = f"❌ 自动登录失败: {str(e)}"
        print(error_msg)
        if TG_TOKEN and TG_CHAT_ID:
            send_tg_notification(TG_TOKEN, TG_CHAT_ID, error_msg)
        return 1

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
