"""Config loading. YAML in config/, secrets and knobs from the environment.

The repo runs more than one brief. A Profile bundles everything that differs
between them: which config files to read, where state and pages live, how many
items a single edition may carry, and how far back a first run looks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
DOCS_DIR = ROOT / "docs"

DEFAULT_REPO = "klhpicture-jpg/daily-brief"


@dataclass(frozen=True)
class Profile:
    name: str
    title: str            # page header and message prefix
    subdir: str           # "" for the daily brief, "id" for the weekly one
    max_items: int
    lookback: timedelta   # window on a first run, and the cap on a long gap

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR / self.subdir if self.subdir else CONFIG_DIR

    @property
    def state_dir(self) -> Path:
        return STATE_DIR / self.subdir if self.subdir else STATE_DIR

    @property
    def docs_dir(self) -> Path:
        return DOCS_DIR / self.subdir if self.subdir else DOCS_DIR

    @property
    def page_prefix(self) -> str:
        return f"{self.subdir}/" if self.subdir else ""


PROFILES = {
    "daily": Profile(
        name="daily",
        title="Daglig brief",
        subdir="",
        max_items=12,
        lookback=timedelta(hours=24),
    ),
    "id": Profile(
        name="id",
        title="ID ugebrief",
        subdir="id",
        max_items=10,
        lookback=timedelta(days=7),
    ),
}
DAILY = PROFILES["daily"]


def profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise SystemExit(f"unknown profile {name!r}, expected one of {sorted(PROFILES)}") from None


def repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO


def pages_base_url() -> str:
    explicit = os.environ.get("PAGES_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    owner, _, name = repo().partition("/")
    return f"https://{owner}.github.io/{name}"


def page_url(profile: Profile, day) -> str:
    return f"{pages_base_url()}/{profile.page_prefix}{day.isoformat()}.html"


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


def load_topics(profile: Profile = DAILY) -> dict:
    return _load_yaml(profile.config_dir / "topics.yaml")


def topics_text(profile: Profile = DAILY) -> str:
    """The ranker and the writer see topics.yaml verbatim, as the file says."""
    return (profile.config_dir / "topics.yaml").read_text(encoding="utf-8")


def load_sources(profile: Profile = DAILY) -> dict:
    return _load_yaml(profile.config_dir / "sources.yaml")


def learned_text(profile: Profile = DAILY) -> str:
    path = profile.config_dir / "learned.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def priority_names(topics: dict) -> list[str]:
    return [str(p.get("name", "")).strip() for p in topics.get("priorities", []) if p.get("name")]
