# `sonya.combine` — GramGPT-style multi-account combine

`sonya` itself ships a single-account Telegram OFM-chatter (modules **4
Neuro-Chatting** and **5 NeuroDialogs** from the [GramGPT](https://gramgpt.io)
feature set). `sonya.combine` is the companion package that adds the remaining
modules so the stack covers the full combine.

| # | Module            | Package                    | Status      |
| - | ----------------- | -------------------------- | ----------- |
| 1 | Account Manager   | `sonya.combine.accounts`   | Sprint 0: pool skeleton. Sprint 1: CRUD + login |
| 2 | Account Warming   | `sonya.combine.warming`    | Planned     |
| 3 | Neuro-Commenting  | `sonya.combine.commenting` | Planned     |
| 4 | Neuro-Chatting    | `sonya.dialogue` (existing) | Shipped    |
| 5 | NeuroDialogs      | `sonya.dialogue` (existing) | Shipped    |
| 6 | Mass Reactions    | `sonya.combine.reactions`  | Planned     |
| 7 | Parsers           | `sonya.combine.parsers`    | Planned     |
| 8 | Analytics         | `sonya.combine.analytics`  | Partly shipped via `sonya_web.dashboard` |

## Data model

Sprint 0 adds three new tables (see `sonya/db/models_combine.py`):

- **`owners`** — single-user deployment seeds id=1; multi-tenant later.
- **`combine_proxies`** — SOCKS5 / HTTP / MTProto proxies, one per-row,
  health-status + latency tracking.
- **`combine_accounts`** — managed Telegram accounts with Telethon
  `StringSession` blob, lifecycle status, role, trust score, FloodWait /
  SpamBlock cool-down timestamps.

Every row is scoped by `owner_id` from day one so flipping on multi-tenancy
never requires another migration.

## Client pool

`sonya.combine.accounts.pool.ClientPool` is an async map of Telethon clients
keyed by account id. It lazily instantiates one client per account on first
`get(account)`, reuses the same client for subsequent lookups, and disconnects
all clients cleanly on `close()`. Tests inject a fake factory so nothing here
depends on live Telegram I/O.

Proxy translation lives in `sonya.combine.accounts.proxy`: given a
`Proxy` row it returns the tuple/dict Telethon's `TelegramClient(proxy=…)`
wants, no hard dependency on `python-socks` at import time.

## Next sprints

1. **Sprint 1 — module 1**: REST router + React page for adding accounts
   (phone / code / 2FA / `.session` import), proxy assignment, health checks.
2. **Sprint 2 — module 2**: warm-up planner + trust score updater.
3. **Sprint 3 — module 7**: 4 parser kinds (users / channels / chats /
   by-message) with arq job queue.
4. **Sprint 4 — module 3**: neuro-commenting campaigns.
5. **Sprint 5 — module 6**: mass reactions.
6. **Sprint 6 — module 8**: analytics aggregator.
7. **Sprint 7**: React + Vite + shadcn/ui front-end, auth, production deploy.
