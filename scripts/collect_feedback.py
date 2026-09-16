"""Weekly feedback rollup: labelled GitHub issues -> config/learned.md.

Reads open issues labelled feedback-good or feedback-bad (title = item title,
body = item hash), asks the writing model for 5 to 10 concise ranking rules,
writes them to config/learned.md, and closes the issues.

    GITHUB_TOKEN=... OPENAI_API_KEY=... python scripts/collect_feedback.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.github_api import paginate, request  # noqa: E402
from src import config  # noqa: E402
from src.llm import Usage, chat_json, no_dashes  # noqa: E402

SYSTEM = """You maintain a short rule file for a news ranker. The reader tagged past digest items
as good (more like this) or bad (less like this). Their standing brief is below.

Turn the feedback into 5 to 10 concise, general rules the ranker can apply to new items.
Each rule is one line, starts with "Prefer" or "Avoid" or "Downrank" or "Uprank", and is
specific enough to act on (name topics, sources, formats). Merge the existing rules with
the new feedback; drop rules the new feedback contradicts. No em dashes.

Return strict JSON: {"rules": ["...", "..."]}"""


def fetch_feedback(repo: str) -> list[dict]:
    rows = []
    for label in ("feedback-good", "feedback-bad"):
        for issue in paginate(f"/repos/{repo}/issues", {"state": "open", "labels": label}):
            if "pull_request" in issue:
                continue
            rows.append({"number": issue["number"], "verdict": "good" if label.endswith("good") else "bad",
                         "title": issue["title"], "hash": (issue.get("body") or "").strip()[:64]})
    return rows


def build_rules(feedback: list[dict], existing: str) -> list[str]:
    user = json.dumps({
        "reader_brief": config.topics_text(),
        "existing_rules": existing,
        "feedback": [{"verdict": f["verdict"], "title": f["title"]} for f in feedback],
    }, ensure_ascii=False)
    usage = Usage()
    data = chat_json(config.write_model(), SYSTEM, user, usage, max_output_tokens=6000, reasoning_effort="low")
    rules = [no_dashes(str(r)).strip() for r in data.get("rules") or [] if str(r).strip()]
    if not 1 <= len(rules) <= 12:
        raise RuntimeError(f"model returned {len(rules)} rules, expected 5 to 10")
    print(f"llm cost ${usage.cost_usd:.4f}")
    return rules[:10]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print rules, do not write or close issues")
    args = p.parse_args()
    repo = config.repo()
    feedback = fetch_feedback(repo)
    if not feedback:
        print("no open feedback issues, nothing to learn")
        return 0
    print(f"{len(feedback)} feedback issues")
    rules = build_rules(feedback, config.learned_text())
    body = f"# Learned rules\n\nAuto-generated from feedback issues on {date.today().isoformat()}. Edit freely, the next rollup merges with this.\n\n"
    body += "".join(f"- {r}\n" for r in rules)
    print(body)
    if args.dry_run:
        return 0
    (config.CONFIG_DIR / "learned.md").write_text(body, encoding="utf-8")
    for f in feedback:
        request("POST", f"/repos/{repo}/issues/{f['number']}/comments", json={"body": "Folded into config/learned.md. Thanks."})
        request("PATCH", f"/repos/{repo}/issues/{f['number']}", json={"state": "closed", "state_reason": "completed"})
    print(f"wrote config/learned.md and closed {len(feedback)} issues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
