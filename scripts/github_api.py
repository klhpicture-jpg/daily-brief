"""Minimal GitHub REST helper shared by the feedback scripts. Needs GITHUB_TOKEN."""
from __future__ import annotations

import os

import requests

API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def request(method: str, path: str, **kwargs) -> requests.Response:
    resp = requests.request(method, f"{API}{path}", headers=_headers(), timeout=30, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub {method} {path} failed: {resp.status_code} {resp.text[:200]}")
    return resp


def paginate(path: str, params: dict | None = None) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        resp = request("GET", path, params={**(params or {}), "per_page": 100, "page": page})
        batch = resp.json()
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
