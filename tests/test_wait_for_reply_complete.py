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

    @property
    def last(self):
        return self

    async def wait_for(self, timeout=None):
        self.waited = True


class MissingPlaceholderEditor:
    @property
    def last(self):
        return self

    async def wait_for(self, timeout=None):
        raise flow.PlaywrightTimeoutError('placeholder not found')


class DummyPage:
    def __init__(self, body_texts, primary_available=True):
        self.body_locator = SequenceBodyLocator(body_texts)
        self.editor = DummyEditor()
        self.primary_available = primary_available
        self.timeouts = []
        self.pressed = []

    def locator(self, selector):
        if selector == 'body':
            return self.body_locator
        if selector == "div[contenteditable='true'][data-placeholder='有什么我能帮你的？']":
            return self.editor if self.primary_available else MissingPlaceholderEditor()
        if selector in {"div[contenteditable='true']", "div[contenteditable='true'][data-placeholder='回复...']"}:
            return self.editor
        raise AssertionError(f'unexpected selector: {selector}')

    async def wait_for_timeout(self, ms):
        self.timeouts.append(ms)

    async def press(self, selector, key):
        self.pressed.append((selector, key))


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
    assert page.timeouts == [3000, 3000]


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
