# `sonya.combine` — GramGPT-style multi-account combine

`sonya` itself ships a single-account Telegram OFM-chatter (modules **4
Neuro-Chatting** and **5 NeuroDialogs** from the [GramGPT](https://gramgpt.io)
feature set). `sonya.combine` is the companion package that adds the remaining
modules so the stack covers the full combine.

| # | Module            | Package                    | Status      |
| - | ----------------- | -------------------------- | ----------- |
| 1 | Account Manager   | `sonya.combine.accounts`   | Sprint 1: CRUD + Telethon login + health check + Fernet session encryption |
| 2 | Account Warming   | `sonya.combine.warming`    | Sprint 2: planner + trust score updater + REST jobs |
| 3 | Neuro-Commenting  | `sonya.combine.commenting` | Planned     |
| 4 | Neuro-Chatting    | `sonya.dialogue` (existing) | Shipped    |
| 5 | NeuroDialogs      | `sonya.dialogue` (existing) | Shipped    |
| 6 | Mass Reactions    | `sonya.combine.reactions`  | Planned     |
| 7 | Parsers           | `sonya.combine.parsers`    | Sprint 3: 4 parser kinds + REST jobs + stub executor |
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

## Sprint 1 — REST API

The FastAPI panel (`sonya_web`) now exposes two routers:

* `/api/combine/proxies` — CRUD + `/check` connectivity probe.
* `/api/combine/accounts` — CRUD + login flow + `/health`.

### Login flow

```
POST /api/combine/accounts/{id}/login/start    -> {login_token, expires_at}
POST /api/combine/accounts/{id}/login/code     -> {login_token, code}
POST /api/combine/accounts/{id}/login/password -> {login_token, password}    # only if 2FA
POST /api/combine/accounts/{id}/import_session -> {session: "<StringSession>"}  # alternative
POST /api/combine/accounts/{id}/logout         -> clears session_blob
POST /api/combine/accounts/{id}/health         -> connect & is_authorized
```

The partial Telethon client lives in :class:`LoginManager`
(`sonya.combine.accounts.login`) keyed by an opaque `login_token`. Tokens
expire after `DEFAULT_TTL` (10 min) and are dropped on success / wrong code
/ explicit cancel. A failed code call invalidates the token; a `2FA needed`
response keeps it alive so the user can finish the flow with `/login/password`.

### Encryption at rest

Set `COMBINE_SECRET_KEY` in `.env` (Fernet key, see `sonya/config.py` doc).
When set:

* `combine_accounts.session_blob` (Telethon `StringSession.save()` output)
* `combine_proxies.password` (outbound proxy auth password)

are encrypted with Fernet before INSERT/UPDATE and decrypted on read via
`sonya.combine.security`. When unset, secrets are stored as-is (acceptable
for local dev only).

## Sprint 2 — Warming module

`sonya.combine.warming` schedules low-risk imitation activity on fresh
accounts so they don't trip Telegram's anti-spam heuristics on day 1.

### Components

* **`WarmingPlanner`** — produces an ordered list of `WarmingAction`
  rows for an account. Risk increases with day index: day 0 is just
  subscribe + read history; reactions appear from ~day 3; idle DMs
  (highest risk) only in the last quarter, and only when
  `idle_chat_targets` is non-empty.
* **`TrustScoreUpdater`** — applies +/- deltas to `Account.trust_score`,
  clamped to 0..100. Marks the parent `WarmingJob` as `RUNNING`/`COMPLETED`
  as actions terminate, and bumps `Account.status` from `NEW` → `WARMING`
  → `ACTIVE` once `trust_score >= job.target_trust_score`.

### REST API (`/api/combine/warming`)

```
GET    /jobs                                  -> list jobs
POST   /jobs                                  -> create job + plan
GET    /jobs/{id}                             -> job + actions
POST   /jobs/{id}/pause   /resume   /cancel   -> lifecycle controls
DELETE /jobs/{id}                             -> remove job
POST   /jobs/{id}/actions/{aid}/complete      -> {success, error?} -> updates trust
```

The `/complete` endpoint is the integration point for the eventual
background executor (Sprint 7): when a Telethon worker subscribes to a
channel, it POSTs the result here and the trust update happens
atomically.

## Sprint 3 — Parsers module

`sonya.combine.parsers` submits four flavours of parsing tasks against a
single account and stores their results so other modules
(warming / commenting / reactions) can use them as input.

### Parser kinds

| `ParserKind`        | Use case                                           |
| ------------------- | -------------------------------------------------- |
| `users_in_chat`     | List members of a public chat / channel.           |
| `channels_of_user`  | List public channels a user has joined.            |
| `chat_history`      | Fetch recent messages in a peer.                   |
| `users_by_message`  | Find authors whose messages match a search query.  |

### Architecture

* **`ParserExecutor`** — `Protocol` describing the runtime that calls
  Telethon. Real implementations are out of scope for Sprint 3 (they
  ship with the worker in Sprint 7).
* **`StubParserExecutor`** — deterministic, offline executor. Used by
  tests and by the `/run-stub` REST endpoint to smoke-test the pipeline
  without a logged-in Telegram account.
* **`combine_parser_jobs` / `combine_parser_results`** — bookkeeping
  tables (alembic ``d8a1c5b9f2e4``).

### REST API (`/api/combine/parsers`)

```
GET    /jobs                              -> list jobs
POST   /jobs                              -> submit a job
GET    /jobs/{id}                         -> job details
DELETE /jobs/{id}                         -> remove job (cascades results)
POST   /jobs/{id}/cancel                  -> mark cancelled (idempotent)
POST   /jobs/{id}/complete                -> {success, error?} -> mark done/failed
GET    /jobs/{id}/results                 -> paginated results (offset/limit)
POST   /jobs/{id}/results                 -> push a batch (executor or operator)
POST   /jobs/{id}/run-stub                -> run StubParserExecutor end-to-end
```

The `/results` and `/complete` endpoints are the integration point for
the future executor: a worker subscribed to the queue picks up pending
jobs, runs Telethon calls, POSTs entities to `/results`, and finally
posts to `/complete`.

## Next sprints

1. **Sprint 4 — module 3**: neuro-commenting campaigns.
2. **Sprint 5 — module 6**: mass reactions.
3. **Sprint 6 — module 8**: analytics aggregator.
4. **Sprint 7**: React + Vite + shadcn/ui front-end, auth, production deploy.
