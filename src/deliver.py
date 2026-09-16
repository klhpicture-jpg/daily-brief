"""Delivery. Telegram is the default (free, no number to rent). Twilio SMS and
WhatsApp stay available behind DELIVERY_CHANNEL.

Telegram: create a bot with @BotFather, send it one message, read your chat id
from https://api.telegram.org/bot<TOKEN>/getUpdates, set TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID. One HTTP call per message, no dependency.

WhatsApp: business-initiated messages outside a 24 hour session window need a
pre-approved Content Template (since April 2025 a plain Body fails with Twilio
error 63016). Set DELIVERY_CHANNEL=whatsapp and TWILIO_CONTENT_SID=HX... and the
message goes out as template variables. Without a Content SID the WhatsApp
path sends a plain Body, which only works inside an open session.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import requests

log = logging.getLogger("deliver")

MAX_CHARS = 480
LINE_MAX = 90
CHANNELS = ("telegram", "sms", "whatsapp")
TELEGRAM_TIMEOUT = 15


def _fit_line(line: str, limit: int) -> str:
    line = " ".join((line or "").split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def build_message(date_label: str, headline: str, lines: list[str], more: int, page_url: str) -> str:
    """The teaser. Top 3 as one line each, then 'N more: link'. Never over 480 chars."""
    lines = [_fit_line(x, LINE_MAX) for x in lines[:3]]
    limit = LINE_MAX
    while True:
        numbered = "\n".join(f"{i + 1}. {_fit_line(x, limit)}" for i, x in enumerate(lines))
        head = f"{date_label} - {_fit_line(headline, 60)}"
        tail = f"+{more} mere: {page_url}" if more > 0 else f"Hele siden: {page_url}"
        parts = [head]
        if numbered:
            parts.append(numbered)
        parts.append(tail)
        message = "\n\n".join(parts)
        if len(message) <= MAX_CHARS or limit <= 30:
            return message
        limit -= 10


def _client():
    from twilio.rest import Client  # lazy so dry runs need no credentials

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(sid, token)


def channel() -> str:
    value = (os.environ.get("DELIVERY_CHANNEL") or "telegram").strip().lower()
    if value not in CHANNELS:
        raise RuntimeError(f"DELIVERY_CHANNEL must be one of {CHANNELS}, got {value!r}")
    return value


def _send_telegram(message: str, silent: bool = False) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": False, "disable_notification": silent},
        timeout=TELEGRAM_TIMEOUT,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {resp.status_code} {data.get('description', resp.text[:200])}")
    message_id = str(data["result"]["message_id"])
    log.info("sent via telegram, message_id %s", message_id)
    return message_id


def _addresses() -> tuple[str, str, str]:
    channel = (os.environ.get("DELIVERY_CHANNEL") or "sms").strip().lower()
    sender = os.environ.get("TWILIO_FROM", "").strip()
    to = os.environ.get("TWILIO_TO", "").strip()
    if not sender or not to:
        raise RuntimeError("TWILIO_FROM and TWILIO_TO must be set")
    if channel == "whatsapp":
        sender = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
        to = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    elif channel != "sms":
        raise RuntimeError(f"DELIVERY_CHANNEL must be sms or whatsapp, got {channel!r}")
    return channel, sender, to


def send(message: str, template_variables: dict | None = None, silent: bool = False) -> str:
    """Send one message. Returns the provider's message id. `silent` skips the
    phone notification on Telegram (used for failure and test messages)."""
    if channel() == "telegram":
        return _send_telegram(message, silent=silent)
    channel_name, sender, to = _addresses()
    client = _client()
    content_sid = os.environ.get("TWILIO_CONTENT_SID", "").strip()
    if channel_name == "whatsapp" and content_sid:
        msg = client.messages.create(
            from_=sender,
            to=to,
            content_sid=content_sid,
            content_variables=json.dumps(template_variables or {"1": message}),
        )
    else:
        if channel_name == "whatsapp":
            log.warning("WhatsApp without TWILIO_CONTENT_SID only works inside an open 24h session")
        msg = client.messages.create(from_=sender, to=to, body=message)
    log.info("sent via %s, sid %s, status %s", channel_name, msg.sid, msg.status)
    return msg.sid


def send_digest(date_label: str, headline: str, lines: list[str], more: int, page_url: str) -> str:
    message = build_message(date_label, headline, lines, more, page_url)
    variables = {"1": f"{date_label} - {headline}"}
    for i in range(3):
        variables[str(i + 2)] = _fit_line(lines[i], LINE_MAX) if i < len(lines) else ""
    variables["5"] = f"+{more} mere: {page_url}"
    return send(message, variables)


def send_failure(run_url: str) -> str:
    message = f"daily-brief fejlede. Log: {run_url}"
    return send(message, {"1": message, "2": "", "3": "", "4": "", "5": ""}, silent=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a test or failure message through the configured channel.")
    parser.add_argument("--failure", action="store_true", help="send the 'digest failed' message")
    parser.add_argument("--run-url", default="", help="link to the failed workflow run")
    parser.add_argument("--test", action="store_true", help="send a short test message")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.failure:
        send_failure(args.run_url or "(no run url)")
    elif args.test:
        send("daily-brief testbesked. Kan du læse det her, virker leveringen.", silent=True)
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
