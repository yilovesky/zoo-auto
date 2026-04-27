import json
from pathlib import Path

import playwright_zo_flow as flow


def test_is_storage_state_file_usable_requires_real_cookie(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'cookies': [], 'origins': []}))
    assert flow.is_storage_state_file_usable(bad) is False

    good = tmp_path / 'good.json'
    good.write_text(json.dumps({'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}], 'origins': []}))
    assert flow.is_storage_state_file_usable(good) is True


def test_choose_auth_strategy_prefers_saved_state_when_usable(tmp_path, monkeypatch):
    state = tmp_path / 'zo_state.json'
    state.write_text(json.dumps({'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}], 'origins': []}))
    monkeypatch.setattr(flow, 'STATE_PATH', state)
    assert flow.choose_auth_strategy() == 'saved_state'


def test_choose_auth_strategy_falls_back_to_magic_link_when_state_missing(tmp_path, monkeypatch):
    state = tmp_path / 'missing.json'
    monkeypatch.setattr(flow, 'STATE_PATH', state)
    assert flow.choose_auth_strategy() == 'magic_link'


def test_create_context_uses_storage_state_when_available(tmp_path, monkeypatch):
    state = tmp_path / 'zo_state.json'
    state.write_text(json.dumps({'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}], 'origins': []}))
    monkeypatch.setattr(flow, 'STATE_PATH', state)

    seen = {}

    class DummyBrowser:
        async def new_context(self, **kwargs):
            seen.update(kwargs)
            return object()

    ctx = flow.asyncio.run(flow.create_context(DummyBrowser()))
    assert ctx is not None
    assert seen['storage_state'] == str(state)
    assert seen['viewport'] == {'width': 1440, 'height': 1100}


def test_create_context_omits_storage_state_when_unusable(tmp_path, monkeypatch):
    state = tmp_path / 'zo_state.json'
    state.write_text(json.dumps({'cookies': [], 'origins': []}))
    monkeypatch.setattr(flow, 'STATE_PATH', state)

    seen = {}

    class DummyBrowser:
        async def new_context(self, **kwargs):
            seen.update(kwargs)
            return object()

    flow.asyncio.run(flow.create_context(DummyBrowser()))
    assert 'storage_state' not in seen
