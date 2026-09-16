"""Config loading. YAML in config/, secrets and knobs from the environment."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
DOCS_DIR = ROOT / "docs"

DEFAULT_REPO = "klhpicture-jpg/daily-brief"


def repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO


def pages_base_url() -> str:
    explicit = os.environ.get("PAGES_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    owner, _, name = repo().partition("/")
    return f"https://{owner}.github.io/{name}"


def rank_model() -> str:
    return os.environ.get("OPENAI_RANK_MODEL", "gpt-5-nano")


def write_model() -> str:
    return os.environ.get("OPENAI_WRITE_MODEL", "gpt-5")


def transcribe_model() -> str:
    return os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return data


def load_topics() -> dict:
    return _load_yaml(CONFIG_DIR / "topics.yaml")


def topics_text() -> str:
    """The ranker and writer see topics.yaml verbatim, as the file says."""
    return (CONFIG_DIR / "topics.yaml").read_text(encoding="utf-8")


def load_sources() -> dict:
    return _load_yaml(CONFIG_DIR / "sources.yaml")


def learned_text() -> str:
    path = CONFIG_DIR / "learned.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def priority_names(topics: dict) -> list[str]:
    return [str(p.get("name", "")).strip() for p in topics.get("priorities", []) if p.get("name")]
