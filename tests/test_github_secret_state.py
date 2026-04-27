import base64
import json
from pathlib import Path

import playwright_zo_flow as flow


def test_env_storage_state_roundtrip(monkeypatch):
    payload = {
        'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}],
        'origins': [],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv('ZO_STORAGE_STATE_B64', encoded)

    assert flow.load_storage_state_from_env() == payload


def test_ensure_storage_state_file_prefers_env_when_file_missing(tmp_path, monkeypatch):
    state_path = tmp_path / 'zo_storage_state.json'
    payload = {
        'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}],
        'origins': [],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv('ZO_STORAGE_STATE_B64', encoded)
    monkeypatch.setattr(flow, 'STATE_PATH', state_path)

    assert flow.ensure_storage_state_file() is True
    assert json.loads(state_path.read_text()) == payload


def test_create_context_uses_env_backed_state_file(tmp_path, monkeypatch):
    state_path = tmp_path / 'zo_storage_state.json'
    payload = {
        'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}],
        'origins': [],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv('ZO_STORAGE_STATE_B64', encoded)
    monkeypatch.setattr(flow, 'STATE_PATH', state_path)

    seen = {}

    class DummyBrowser:
        async def new_context(self, **kwargs):
            seen.update(kwargs)
            return object()

    flow.asyncio.run(flow.create_context(DummyBrowser()))
    assert seen['storage_state'] == str(state_path)


def test_serialize_storage_state_for_github_secret_returns_base64(tmp_path):
    state_path = tmp_path / 'zo_storage_state.json'
    payload = {
        'cookies': [{'name': 'session', 'value': 'abc', 'domain': '.zo.computer', 'path': '/'}],
        'origins': [],
    }
    state_path.write_text(json.dumps(payload))

    encoded = flow.serialize_storage_state_for_github_secret(state_path)
    decoded = json.loads(base64.b64decode(encoded).decode())
    assert decoded == payload


def test_build_github_secret_update_payload_includes_storage_secret(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_example')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'yilovesky/zoo-auto')

    payload = flow.build_github_secret_update_payload('abc123')

    assert payload['token'] == 'ghp_example'
    assert payload['owner'] == 'yilovesky'
    assert payload['repo'] == 'zoo-auto'
    assert payload['secret_name'] == 'ZO_STORAGE_STATE_B64'
    assert payload['secret_value'] == 'abc123'
