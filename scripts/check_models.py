"""List the OpenAI models this key can use, and check the configured defaults.

    python scripts/check_models.py

Run this before trusting any model ID in .env or the workflow.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402

INTERESTING = re.compile(r"(gpt-5|gpt-4\.1|mini|nano|transcribe|whisper)")


def main() -> int:
    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    ids = sorted(m.id for m in OpenAI().models.list())
    print(f"{len(ids)} models available. Likely candidates:")
    for mid in ids:
        if INTERESTING.search(mid):
            print("  ", mid)
    print("\nAll models:")
    for mid in ids:
        print("  ", mid)
    print("\nConfigured defaults:")
    ok = True
    for label, mid in (("rank", config.rank_model()), ("write", config.write_model()), ("transcribe", config.transcribe_model())):
        exists = mid in ids
        ok = ok and exists
        print(f"  {label:10s} {mid:32s} {'ok' if exists else 'NOT FOUND, change OPENAI_' + label.upper() + '_MODEL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
