"""Diagnose the delivery and LLM secrets without sending a digest.

    python scripts/check_setup.py

Prints what the bot token can see (bot name, chat ids that have messaged it)
and whether the OpenAI key has credit. Never prints the secrets themselves.
"""
from __future__ import annotations

import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402


def check_telegram() -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    print("== Telegram ==")
    if not token:
        print("FAIL TELEGRAM_BOT_TOKEN is empty")
        return False
    if ":" not in token or len(token) < 40:
        print(f"FAIL TELEGRAM_BOT_TOKEN looks wrong ({len(token)} chars, expected like 123456789:AAH...)")
        return False
    me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    if not me.get("ok"):
        print(f"FAIL token rejected by Telegram: {me.get('description')}")
        return False
    print(f"OK   bot is @{me['result']['username']}")

    updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
    seen = {}
    for u in updates.get("result", []):
        msg = u.get("message") or u.get("edited_message") or u.get("my_chat_member", {}) or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            seen[str(chat["id"])] = chat.get("first_name") or chat.get("title") or chat.get("type")
    if seen:
        print("OK   chats that have messaged this bot: " + ", ".join(f"{cid} ({name})" for cid, name in seen.items()))
    else:
        print("WARN nobody has messaged this bot yet (or the messages are older than 24h). Open @"
              f"{me['result']['username']} in Telegram, press Start, send 'hej', then rerun.")

    if not chat_id:
        print("FAIL TELEGRAM_CHAT_ID is empty")
        return False
    if not chat_id.lstrip("-").isdigit():
        print(f"FAIL TELEGRAM_CHAT_ID is not a number ({len(chat_id)} chars). Copy only the digits.")
        return False
    print(f"     configured TELEGRAM_CHAT_ID: {chat_id[:2]}...{chat_id[-2:]} ({len(chat_id)} digits)")
    if seen and chat_id not in seen:
        print("FAIL the configured chat id is not one of the chats above. Use one of those.")
        return False
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": chat_id, "text": "daily-brief setup check: Telegram works."}, timeout=15).json()
    if resp.get("ok"):
        print("OK   test message sent, check your phone")
        return True
    print(f"FAIL sendMessage: {resp.get('description')}")
    return False


def check_openai() -> bool:
    print("== OpenAI ==")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("FAIL OPENAI_API_KEY is empty")
        return False
    print(f"     key starts with {key[:7]}... ({len(key)} chars)")
    from openai import OpenAI

    client = OpenAI()
    try:
        ids = sorted(m.id for m in client.models.list())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL key rejected: {type(exc).__name__}: {str(exc)[:200]}")
        return False
    print(f"OK   key accepted, {len(ids)} models visible")
    ok = True
    for label, mid in (("rank", config.rank_model()), ("write", config.write_model())):
        if mid in ids:
            print(f"OK   {label} model {mid} exists")
        else:
            ok = False
            close = [m for m in ids if mid.split("-")[0] in m][:8]
            print(f"FAIL {label} model {mid} not found. Similar: {', '.join(close) or 'none'}")
    try:
        r = client.chat.completions.create(model=config.rank_model(), messages=[{"role": "user", "content": "Reply with OK"}], max_completion_tokens=20)
        print(f"OK   test call answered: {(r.choices[0].message.content or '').strip()[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "credit" in text or "quota" in text:
            print("FAIL no credit on this key's organization. Add credit at platform.openai.com, Settings, Billing, "
                  "and make sure the key belongs to the same organization and project that holds the credit.")
        else:
            print(f"FAIL test call: {type(exc).__name__}: {text[:200]}")
        ok = False
    return ok


def main() -> int:
    t = check_telegram()
    print()
    o = check_openai()
    print()
    print("ALL GOOD" if t and o else "SOMETHING TO FIX, see FAIL lines above")
    return 0 if t and o else 1


if __name__ == "__main__":
    sys.exit(main())
