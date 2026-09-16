"""Create the two feedback labels if they are missing. Idempotent.

    GITHUB_TOKEN=... python scripts/ensure_labels.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.github_api import request  # noqa: E402
from src import config  # noqa: E402

LABELS = {
    "feedback-good": ("0e8a16", "More like this"),
    "feedback-bad": ("d73a4a", "Less like this"),
}


def main() -> int:
    repo = config.repo()
    existing = {l["name"] for l in request("GET", f"/repos/{repo}/labels", params={"per_page": 100}).json()}
    for name, (color, description) in LABELS.items():
        if name in existing:
            print(f"label {name} exists")
            continue
        request("POST", f"/repos/{repo}/labels", json={"name": name, "color": color, "description": description})
        print(f"created label {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
