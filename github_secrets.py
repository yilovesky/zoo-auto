#!/usr/bin/env python3
import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


SECRET_NAME = "ZO_STORAGE_STATE_B64"


def parse_github_repository(repo_ref: str | None) -> tuple[str, str]:
    if not repo_ref or "/" not in repo_ref:
        raise ValueError("GITHUB_REPOSITORY must look like owner/repo")
    owner, repo = repo_ref.split("/", 1)
    if not owner or not repo:
        raise ValueError("GITHUB_REPOSITORY must look like owner/repo")
    return owner, repo


def load_storage_state_from_env() -> dict | None:
    encoded = os.getenv(SECRET_NAME, "").strip()
    if not encoded:
        return None
    data = json.loads(base64.b64decode(encoded).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Decoded storage state must be a JSON object")
    return data


def write_storage_state_if_present(path: Path) -> bool:
    data = load_storage_state_from_env()
    if not data:
        return False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return True


def serialize_storage_state_for_github_secret(path: Path) -> str:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Storage state file must contain a JSON object")
    return base64.b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8")).decode("ascii")


def build_github_secret_update_payload(secret_value: str) -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    owner, repo = parse_github_repository(os.getenv("GITHUB_REPOSITORY"))
    if not token:
        raise ValueError("GITHUB_TOKEN is required to update GitHub secrets")
    return {
        "token": token,
        "owner": owner,
        "repo": repo,
        "secret_name": SECRET_NAME,
        "secret_value": secret_value,
    }


def _github_api_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "zoo-auto",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _put_github_secret(url: str, token: str, body: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "zoo-auto",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30):
        return


def update_github_storage_secret_if_possible(path: Path) -> bool:
    if not path.exists():
        return False
    secret_value = serialize_storage_state_for_github_secret(path)
    try:
        payload = build_github_secret_update_payload(secret_value)
    except ValueError:
        return False

    token = payload["token"]
    owner = payload["owner"]
    repo = payload["repo"]
    info = _github_api_json(
        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key",
        token,
    )

    try:
        from nacl import encoding, public
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyNaCl is required to update GitHub secrets") from exc

    sealed_box = public.SealedBox(
        public.PublicKey(info["key"].encode("utf-8"), encoding.Base64Encoder)
    )
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    body = {
        "encrypted_value": base64.b64encode(encrypted).decode("ascii"),
        "key_id": info["key_id"],
    }
    _put_github_secret(
        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{SECRET_NAME}",
        token,
        body,
    )
    return True
