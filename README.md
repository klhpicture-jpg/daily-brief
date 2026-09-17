# daily-brief

A personal daily intelligence digest. Every morning a GitHub Action collects
RSS (podcasts and web watch come in later phases), scores every item with a
cheap model against `config/topics.yaml`, has a stronger model write only the
survivors, publishes a mobile-first page to GitHub Pages and sends a three line teaser
with the link to Telegram (or SMS).

Read on a phone, in under two minutes. That constraint drives every decision.

## Setup in 6 steps

1. **Secrets.** In the repo, Settings, Secrets and variables, Actions: add the secrets from the table below.
2. **Pages.** Settings, Pages: source "Deploy from a branch", branch `main`, folder `/docs`. Note: on a free personal GitHub plan, Pages only works on public repos. Either make the repo public (secrets stay secret, the digest pages do not) or use GitHub Pro.
3. **Models.** Run `python scripts/check_models.py` locally with your `OPENAI_API_KEY` and set the repo variables `OPENAI_RANK_MODEL` and `OPENAI_WRITE_MODEL` (Settings, Variables) to IDs that exist. Defaults are `gpt-5-nano` and `gpt-5`.
4. **Sources.** Run the "check sources" workflow (Actions tab) once and delete any feed it flags.
5. **Check.** Run the "check setup" workflow (Actions tab). It tells you in plain words if a secret is wrong and sends a test message to Telegram.
6. **First run.** Run the "digest" workflow with `dry_run` checked, open the run log and read the message it would have sent. Then run it unchecked. The scheduled run is 18:25 Europe/Copenhagen daily, year round (two UTC cron slots, `scripts/gate.py` lets one through). GitHub's scheduler is best effort and often starts a run 15 minutes to 3 hours late, so the gate accepts any run from 18:00 local until midnight and a marker file (`state/last_scheduled.txt`) keeps it to one delivery per day. A run delayed past midnight is skipped; the next evening covers the gap because the window starts at the last successful run. Only the digest itself rings the phone; failure and test messages arrive silently.

Local run: `pip install -r requirements.txt`, copy `.env.example` to `.env`, export it, then
`python -m src.main --dry-run` (real feeds, real LLM, no delivery, page in a temp folder) or
`python -m src.main --dry-run --no-llm` (free, stubbed ranking and writing). Tests: `pip install pytest && python -m pytest`.

## Secrets

| Secret | Used for |
|---|---|
| `OPENAI_API_KEY` | ranking, writing, transcription (phase 2), feedback rollup |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | delivery, the default channel |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | delivery via SMS or WhatsApp only |
| `TWILIO_FROM`, `TWILIO_TO` | sender number and your phone, E.164 (`+45...`), SMS or WhatsApp only |
| `TWILIO_CONTENT_SID` | only for WhatsApp, the approved template SID (`HX...`) |
| `FIRECRAWL_API_KEY` | web watch (phase 3) |
| `APIFY_TOKEN` | LinkedIn (phase 4) |

Repo variables (not secrets): `DELIVERY_CHANNEL` (`telegram`, the default, `sms` or `whatsapp`), `OPENAI_RANK_MODEL`, `OPENAI_WRITE_MODEL`, `OPENAI_TRANSCRIBE_MODEL`.

## Two briefs

| | Daily brief | ID weekly |
|---|---|---|
| Profile | `daily` | `id` |
| For | Kasper: AI, marketing, retail, Europe, sport | ID Identity (Rexholm): competitors, textile regulation, the promo and workwear trade |
| When | every day, 18:25 Europe/Copenhagen | Monday, 18:40 Europe/Copenhagen |
| Window | since the last run, at most 24h | since the last run, at most 7 days |
| Items | up to 12 | up to 10 |
| Config | `config/` | `config/id/` |
| Pages | `/` | `/id/` |
| Workflow | `digest.yml` | `weekly.yml` |

Both go to the same Telegram chat. The message is prefixed with the brief's name.
Run either by hand from the Actions tab, or locally with `python -m src.main --profile id`.

**An empty edition sends nothing.** If no item clears the ranker's bar, the run writes no page,
sends no message and leaves the previous edition in place. It only records the run. That matters
most for the weekly brief, where a quiet week in the trade press is normal and a message saying
"nothing happened" is worse than no message.

## Add a source

Add one line to `config/sources.yaml` (or `config/id/sources.yaml` for the weekly brief) and commit. A broken source never kills the run: it is
listed in the page footer instead. Run the "check sources" workflow after editing and pick the profile in the dropdown.

- **Anything with a feed** goes under `rss`. Free. Substack: append `/feed` to the URL. Acast
  podcasts: `feeds.acast.com/public/shows/<show>`.
- **Podcasts** go under `podcasts`. Show notes are collected for free. `transcribe: true` turns on
  full transcription (phase 2), about 0.02 USD per 10 minutes of audio; `max_minutes` caps it.
- **Email-only newsletters** (TLDR AI, Politico Playbook): create a feed at kill-the-newsletter.com,
  subscribe with the address it gives you, paste the feed URL under `rss`.
- **Paywalled sites**: skip them, their podcasts are usually free.
- **Feedless pages** go under `web_watch` (phase 3, Firecrawl).

## Change topics

Edit `config/topics.yaml`, or `config/id/topics.yaml` for the weekly industry brief. The ranker and the writer see the file verbatim, so write it
like a brief to a smart assistant: who you are, what you care about in priority order, what
to exclude. No code changes, the next run picks it up.

## Feedback loop

Every item on the page has a thumbs up and a thumbs down link. Tapping one opens a
prefilled GitHub issue (label `feedback-good` or `feedback-bad`, title = item, body = item
hash). Just hit submit. Every Monday `learn.yml` reads the open feedback issues, asks the
writing model to fold them into 5 to 10 rules in `config/learned.md`, closes the issues and
commits. The ranker reads `learned.md` on every run, so the digest gets sharper instead of
getting muted. Edit `learned.md` by hand any time.

## Delivery

Telegram is the default: free, no number to rent, push notification on the phone.

1. In Telegram, message @BotFather, send `/newbot`, follow the prompts, copy the token.
2. Open a chat with your new bot and send it any message (a bot cannot message you first).
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `chat.id` from the JSON.
4. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repo secrets.
5. Test it: `DELIVERY_CHANNEL=telegram python -m src.deliver --test` locally, or run the digest workflow.

SMS is behind `DELIVERY_CHANNEL=sms` (Twilio, roughly 0.05 USD per segment to Denmark, a
480 character teaser is 3 to 4 segments). WhatsApp is behind `DELIVERY_CHANNEL=whatsapp`:
business-initiated WhatsApp messages outside a 24 hour session window must use a
pre-approved Content Template, sent with `ContentSid` and `ContentVariables` (plain `Body`
fails with Twilio error 63016 since April 2025). Create a template in the Twilio Content
Template Builder with five variables (`{{1}}` date and headline, `{{2}}` to `{{4}}` the
three lines, `{{5}}` the "N more" link), get it approved by Meta, and set
`TWILIO_CONTENT_SID`. Meta bills per template message (utility or marketing category),
check current pricing before switching.

## Cost

The page footer shows the estimated LLM cost per run, from token counts times the price
table in `src/llm.py`. Verify those prices against the OpenAI pricing page; unknown models
are counted as zero with a warning in the log. A typical run with 15 feeds is a few cents.

## Layout

```
config/topics.yaml     what I care about, the highest leverage file
config/sources.yaml    feeds, pages, accounts
config/learned.md      auto-generated from feedback
config/id/             the same three files for the weekly ID industry brief
scripts/gate.py        decides whether a scheduled slot runs (DST, delays, once per period)
src/collectors/        one module per source type, all emit the same Item
src/rank.py            stage 1, cheap model scores everything
src/digest.py          stage 2, strong model writes the survivors
src/render.py          the page
src/deliver.py         Twilio
src/main.py            orchestrator
state/seen.json        hashes already shown, committed back by the workflow
state/runs.jsonl       one line per run: counts, errors, cost, whether it delivered
state/id/              the same state for the weekly brief
docs/                  GitHub Pages output, one file per edition plus index and archive
docs/id/               the weekly brief's pages
```
