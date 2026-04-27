import playwright_zo_flow as flow


class SequenceBodyLocator:
    def __init__(self, texts):
        self._texts = list(texts)
        self._idx = 0

    async def inner_text(self):
        if self._idx < len(self._texts) - 1:
            value = self._texts[self._idx]
            self._idx += 1
            return value
        return self._texts[-1]


class DummyEditor:
    def __init__(self):
        self.waited = False
        self.clicked = []

    @property
    def last(self):
        return self

    async def wait_for(self, timeout=None):
        self.waited = True

    async def click(self, force=False):
        self.clicked.append(force)


class MissingPlaceholderEditor:
    @property
    def last(self):
        return self

    async def wait_for(self, timeout=None):
        raise flow.PlaywrightTimeoutError('placeholder not found')


class DummyPage:
    def __init__(self, body_texts, primary_available=True, reply_available=True, send_button_available=False):
        self.body_locator = SequenceBodyLocator(body_texts)
        self.editor = DummyEditor()
        self.send_button = DummyEditor()
        self.primary_available = primary_available
        self.reply_available = reply_available
        self.send_button_available = send_button_available
        self.timeouts = []
        self.pressed = []
        self.keyboard_presses = []
        self.keyboard_typed = []
        self.keyboard = self

    def locator(self, selector):
        if selector == 'body':
            return self.body_locator
        if selector == "div[contenteditable='true'][data-placeholder='有什么我能帮你的？']":
            return self.editor if self.primary_available else MissingPlaceholderEditor()
        if selector == "div[contenteditable='true'][data-placeholder='回复...']":
            return self.editor if self.reply_available else MissingPlaceholderEditor()
        if selector in {
            "div[contenteditable='true']",
            'div.tiptap.ProseMirror',
        }:
            return self.editor
        if selector in {"button[type='submit']", "button[aria-label='Send message']", "button[aria-label='发送']", "button:has(svg)"}:
            return self.send_button if self.send_button_available else MissingPlaceholderEditor()
        raise AssertionError(f'unexpected selector: {selector}')

    async def wait_for_timeout(self, ms):
        self.timeouts.append(ms)

    async def type(self, text):
        self.keyboard_typed.append(text)

    async def press(self, *args):
        if len(args) == 2:
            selector, key = args
            self.pressed.append((selector, key))
        elif len(args) == 1:
            self.keyboard_presses.append(args[0])
        else:
            raise TypeError(f'unexpected args: {args}')


def test_try_send_prompt_waits_until_reply_complete(monkeypatch):
    page = DummyPage([
        'before send',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\n最终回复内容',
    ])

    calls = []

    async def fake_fill(editor, page_obj, text):
        calls.append((editor, page_obj, text))

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is True
    assert '最终回复内容' in body
    assert calls == [(page.editor, page, flow.PROMPT)]
    assert page.pressed == [("div[contenteditable='true'][data-placeholder='有什么我能帮你的？']", 'Enter')]
    assert page.timeouts == [3000]


def test_try_send_prompt_uses_reply_placeholder_fallback(monkeypatch):
    page = DummyPage([
        'before send',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\n最终回复内容',
    ], primary_available=False)

    calls = []

    async def fake_fill(editor, page_obj, text):
        calls.append((editor, page_obj, text))

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is True
    assert '最终回复内容' in body
    assert calls == [(page.editor, page, flow.PROMPT)]
    assert page.pressed == [("div[contenteditable='true'][data-placeholder='回复...']", 'Enter')]


def test_try_send_prompt_clicks_send_button_if_enter_does_not_submit(monkeypatch):
    page = DummyPage([
        'before send',
        'before send',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\n最终回复内容',
    ], send_button_available=True)

    async def fake_fill(editor, page_obj, text):
        return None

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is True
    assert '最终回复内容' in body
    assert page.pressed == [("div[contenteditable='true'][data-placeholder='有什么我能帮你的？']", 'Enter')]
    assert page.send_button.clicked == [True]
    assert page.timeouts == [1000, 3000, 3000]


def test_try_send_prompt_succeeds_when_ui_transitions_to_reply_state_without_echoing_prompt(monkeypatch):
    page = DummyPage([
        'before send\n有什么我能帮你的？',
        'before send\nZo is thinking. Press Esc to stop.\n回复...',
        '加载中...\nZo is thinking. Press Esc to stop.\n回复...',
        '最终回复内容\n最新域名: https://abc123.trycloudflare.com',
    ])

    async def fake_fill(editor, page_obj, text):
        return None

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is True
    assert 'https://abc123.trycloudflare.com' in body
    assert page.pressed == [("div[contenteditable='true'][data-placeholder='有什么我能帮你的？']", 'Enter')]


def test_try_send_prompt_times_out_if_reply_never_finishes(monkeypatch):
    page = DummyPage([
        'before send',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\nZo is thinking',
    ])

    async def fake_fill(editor, page_obj, text):
        return None

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    values = iter([0, 1, 2, 181])
    monkeypatch.setattr(flow.time, 'time', lambda: next(values))

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is False
    assert 'Zo is thinking' in body
    assert page.pressed == [("div[contenteditable='true'][data-placeholder='有什么我能帮你的？']", 'Enter')]


def test_fill_prosemirror_falls_back_to_keyboard_typing_when_fill_does_not_stick():
    class EditorThatIgnoresFill(DummyEditor):
        def __init__(self):
            super().__init__()
            self.fill_calls = []

        async def fill(self, text):
            self.fill_calls.append(text)

        async def inner_text(self):
            return ''

    page = DummyPage(['before send'])
    editor = EditorThatIgnoresFill()

    flow.asyncio.run(flow.fill_prosemirror(editor, page, flow.PROMPT))

    assert editor.fill_calls == [flow.PROMPT]
    assert page.keyboard_presses == ['Control+A', 'Meta+A']
    assert page.keyboard_typed == [flow.PROMPT]
    assert page.timeouts == [1000]


def test_try_send_prompt_falls_back_to_generic_prosemirror_selector(monkeypatch):
    page = DummyPage([
        'before send',
        f'before send\n{flow.PROMPT}\nZo is thinking',
        f'before send\n{flow.PROMPT}\n最终回复内容',
    ], primary_available=False, reply_available=False)

    async def fake_fill(editor, page_obj, text):
        return None

    monkeypatch.setattr(flow, 'fill_prosemirror', fake_fill)

    sent, body = flow.asyncio.run(flow.try_send_prompt(page))

    assert sent is True
    assert '最终回复内容' in body
    assert page.pressed == [('div.tiptap.ProseMirror', 'Enter')]


def test_prompt_text_matches_exact_multiline_instruction():
    assert flow.PROMPT == """你先帮我重启我的哪吒探针agent.sh，确保哪吒探针agent.sh在运行后再帮我依次运行下面的代码，并发给我日志中显示的最新的域名

nohup /usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8000 >> /opt/openai-cpa/cf.log 2>&1 &

cd /opt/openai-cpa && source venv/bin/activate

nohup python wfxl_openai_regst.py >> /opt/openai-cpa/run.log 2>&1 &

grep -o 'https://.*\\.trycloudflare\\.com' /opt/openai-cpa/cf.log"""


def test_success_caption_includes_copyable_domain():
    body = "执行完成\n最新域名: https://abc123.trycloudflare.com\n其余输出"
    assert flow.build_success_caption(body) == "最新域名: https://abc123.trycloudflare.com"


def test_success_caption_falls_back_when_no_domain_found():
    assert flow.build_success_caption("无域名") == "Zo 自动流程成功截图"
