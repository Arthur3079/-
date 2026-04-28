# Sonya operations runbook

This is a short, operator-facing manual: how to deploy, what to check first
when things look wrong, and how to use the admin chat to take over a
conversation.

> Status: MVP — this runbook reflects what's actually wired in code at this
> commit. Don't promise users anything that isn't listed here.

---

## 1. Architecture at a glance

Two long-running Python processes share one database:

| Process | Module | What it does |
|---|---|---|
| `sonya` | `python -m sonya.main` | Telethon userbot. Reads/writes DMs, runs `DialogueService`, talks to the LLM, runs the cadence engine, owns the admin chat. |
| `payment_bot` | `python -m sonya.payment_bot.main` | Telegram Bot API process. Owns `PAY_BOT_TOKEN`. Sends invoices, handles `pre_checkout_query` + `successful_payment`, writes `payment_events` and `content_deliveries`. Exits 2 (graceful) when token is missing. |

Both processes run alembic-migrated Postgres or SQLite (default). Migrations
run automatically on `sonya` startup; the payment bot expects them to be up.

State that **must** persist across restarts:

- `data/sonya.db` (SQLite) — clients, messages, facts, content_sets, sales,
  payment_events, deliveries, admin_actions, followups.
- `sessions/sonya.session` — Telethon login session for the userbot. Loss of
  this file requires re-logging the user account (phone + 2FA).
- `logs/` — application logs (also rotated, see §4).

---

## 2. Configuration (`.env`)

Copy `.env.example` to `.env` and fill in:

| Var | Required | Notes |
|---|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | yes | From my.telegram.org. |
| `LLM_PROVIDER` | yes | `openai_compat` or `gemini`. |
| `LLM_API_KEY` | yes | Provider-specific. |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` | optional | Override per-provider. |
| `PAY_BOT_TOKEN` | optional | Empty → sales engine runs in DRY mode (logs "would create invoice"). |
| `PAY_BOT_USERNAME` | optional | The bot's `@username` for CTA links. |
| `ADMIN_USER_IDS` | optional | CSV of Telegram user IDs allowed to send admin commands. Empty → no admin chat. |
| `DRY_RUN` | dev only | When `true`, never actually sends to Telegram. |
| `INCOMING_DEBOUNCE_SECONDS` | optional | Default 3.0. Bursts of incoming texts within this window collapse into one reply. |
| `MAX_REPLY_BUBBLES` | optional | Default 2. How many short messages one reply may split into. |

---

## 3. Deploy

### 3.1. Docker (recommended)

```bash
git clone https://github.com/pvrmj88vmj-ops/AI-tg.git
cd AI-tg
cp .env.example .env  # then fill in
mkdir -p sessions data logs
docker compose up -d
```

First start: `sonya` will prompt for Telegram login code. You need to attach
once with `docker compose run --rm -it sonya python -m sonya.main` to enter
the SMS code; after that the session file is on disk and the service auto-
restarts cleanly.

### 3.2. systemd

```bash
sudo useradd --system --create-home --home /opt/sonya sonya
sudo mkdir -p /opt/sonya /var/log/sonya
sudo chown -R sonya:sonya /opt/sonya /var/log/sonya
sudo -u sonya git clone https://github.com/pvrmj88vmj-ops/AI-tg.git /opt/sonya
cd /opt/sonya
sudo -u sonya python3.11 -m venv .venv
sudo -u sonya .venv/bin/pip install .
sudo -u sonya cp .env.example .env  # then edit
sudo -u sonya .venv/bin/alembic upgrade head

sudo cp deploy/sonya.service /etc/systemd/system/
sudo cp deploy/sonya-payment-bot.service /etc/systemd/system/
sudo cp deploy/sonya.logrotate /etc/logrotate.d/sonya
sudo systemctl daemon-reload
sudo systemctl enable --now sonya
sudo systemctl enable --now sonya-payment-bot   # safe even without PAY_BOT_TOKEN
```

Check: `journalctl -u sonya -n 100 --no-pager`.

---

## 4. Logs

| Path | Source |
|---|---|
| `logs/sonya.log` (Docker volume `sonya-logs`) or `/var/log/sonya/sonya.log` (systemd) | Userbot |
| `/var/log/sonya/payment-bot.log` (systemd) | Payment bot |

Rotation is daily, 14 generations, gzipped. See `deploy/sonya.logrotate`.

For ad-hoc debugging:

```bash
docker compose logs -f sonya
docker compose logs -f payment_bot
journalctl -u sonya -f
```

---

## 5. Admin chat

If you set `ADMIN_USER_IDS=<your_tg_id>` in `.env`, you can DM the userbot
from your own Telegram account and use commands.

| Command | Effect |
|---|---|
| `/help` | List commands. |
| `/status` | Total clients, paused fans, recent admin actions, 24h message count, 7d purchases, pending followups. |
| `/pause <fan_id> [reason]` | Stop auto-replies for that fan. |
| `/resume <fan_id>` | Re-enable auto-replies. |
| `/handoff <fan_id> [reason]` | Same as pause but tags reason `handoff:`. |
| `/card <fan_id>` | Render full client card: name, fan_type, language, spend, flags, facts, notes, last message. |
| `/facts <fan_id>` | List the CRM facts the bot knows. |
| `/note <fan_id> <text>` | Append a timestamped note to the client. |
| `/dump_prompt <fan_id>` | Show the system prompt that *would* be sent next (no LLM call). |

Every command writes to the `admin_actions` audit table.

---

## 6. Common incidents

### "The bot stopped replying"

1. `/status` from your admin account. Is `paused` count high? Did you (or
   another operator) `/pause` someone by mistake?
2. Check logs for `FloodWait` / `RPCError` — those are expected during
   bursts; the runtime backs off automatically (`runtime/telegram_io.py`).
3. Check `LLM_API_KEY` validity (provider quotas).

### "A fan paid but didn't receive content"

1. `payment_events` table will have a `successful` row if Telegram confirmed
   it. Cross-reference `invoice_payload` to a `sales_attempts` row.
2. `content_deliveries` row should exist with `delivery_status='pending'`.
   The userbot delivers files asynchronously — if delivery is stuck,
   re-deliver manually and update the row.
3. Use `/card <fan_id>` to confirm the bot sees the fan's lifetime spend bumped.

### "Sonya is being sent to a paused fan anyway"

`is_paused` is checked **before** the dialogue service runs. If you see
auto-replies despite a pause, check that the message was indeed processed
*after* the pause: look at `clients.is_paused` directly with sqlite3 or psql.

### Resetting

```bash
docker compose down
sudo rm -rf data/  # ⚠ destroys all CRM/history. Keep `sessions/` and `.env`.
docker compose up -d
```

---

## 7. Tests / pre-deploy checklist

```bash
ruff check .
ruff format --check .
pytest -q
alembic upgrade head     # ensure migrations are clean
python -m sonya.main &   # smoke (DRY_RUN=true)
```

Pre-prod checklist:
- [ ] `.env` filled in (no `dry_run=true` for prod userbot)
- [ ] `data/` and `sessions/` are on a persistent volume
- [ ] `ADMIN_USER_IDS` includes the on-call operator's tg id
- [ ] Log rotation in place (`/etc/logrotate.d/sonya`)
- [ ] Backup of `data/sonya.db` scheduled (cron + offsite copy)
