# Sonya — AI Telegram OFM-чаттер

> Userbot-аккаунт «Соня» в Telegram, ведёт переписку как живой человек, будет продавать PPV-контент за Telegram Stars. Под капотом — OpenAI-совместимый LLM (OpenRouter / NVIDIA / Groq / DeepSeek / OpenAI) **или** Google Gemini, Telethon и SQLite/PostgreSQL.

**Текущий статус: end-to-end runtime.** Работают Telegram-userbot, LLM-слой,
структурированная safety-engine v2 (включая stop-request, harassment,
intoxication, chargeback), журней-движок (welcome → warmup → qualify →
offer_pending → aftercare → repeat_ready → ghost), cadence-движок (gating
sales-офферов и proactive-followups), Telegram Stars sales lifecycle,
auto-aftercare после оплаты, scheduler с pre-send re-check, admin-чат
(`/pause`, `/handoff`, `/card`, `/facts`, `/note`, `/dump_prompt`), полный
deploy (Dockerfile / compose / systemd). **Отложено:** автоматическое
fact-extraction, structured-LLM output, voice/image understanding. Подробный
план — см. [дорожную карту](#дорожная-карта).

---

## Что внутри

- `sonya/` — основной код (Python 3.11+).
- `knowledge/` — обучающая база Сони (персона, плейбуки, каталог 47 контент-сетов, fine-tune датасет). Read-only.
- `migrations/` — Alembic-миграции БД.
- `tests/` — pytest.
- `.env.example` — шаблон конфига. Скопируй в `.env` и заполни своими ключами.

---

## Быстрый старт (Windows + VS Code)

### 1. Установить Python 3.11+

Скачай с [python.org](https://www.python.org/downloads/) **Python 3.11** или новее. При установке поставь галку **«Add python.exe to PATH»**.

Проверь:
```powershell
python --version
```
Должно быть `Python 3.11.x` или выше.

### 2. Установить Git и склонировать репо

```powershell
git clone https://github.com/pvrmj88vmj-ops/AI-tg.git
cd AI-tg
```

### 3. Открыть в VS Code

```powershell
code .
```

В VS Code установи расширения (он сам предложит):
- **Python** (Microsoft)
- **Pylance** (Microsoft)
- **Ruff** (Astral Software)

### 4. Создать виртуальное окружение и поставить зависимости

В терминале (`` Ctrl+` `` в VS Code или `Alt+F12` в PyCharm):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

> Если в PowerShell ругается на `activate` — выполни один раз:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> Подтверди `Y`, потом снова `.venv\Scripts\activate`.

> Альтернатива без активации (если PowerShell всё равно капризничает):
> ```powershell
> .venv\Scripts\python.exe -m pip install --upgrade pip
> .venv\Scripts\python.exe -m pip install -r requirements.txt
> ```

### 5. Создать конфиг

```powershell
copy .env.example .env
```

Открой `.env` в VS Code. Для первого smoke-запуска ключи можно не заполнять — запустится в «no-Telegram mode» (только покажет warning'и). По умолчанию `DRY_RUN=true`: входящие будут логироваться, но **отправка ответов выключена**, пока сам не поменяешь.

### 6. Применить миграции БД (создаст файл `sonya.db`)

```powershell
alembic upgrade head
```

### 7. Запустить

```powershell
python -m sonya.main
```

Должен увидеть в терминале:
```
INFO     Knowledge index: 1788 chunks from 35/35 markdown files (...)
SUCCESS  Sonya is ready (no-Telegram mode).
```
(Если ключи Telegram/LLM ещё не заданы — это нормальный статус для smoke-запуска.)

Из VS Code также можно нажать **F5** или кнопку «Run Python File» на `sonya/main.py`.

---

## Веб-панель (локально)

Минимальный admin UI для наблюдения за ботом: KPI, фаны, воронка, safety,
scheduler, live-события из `events_log` через SSE. Без авторизации — только
для локального использования, наружу не выставлять.

```powershell
pip install -e ".[web]"
alembic upgrade head
python -m sonya_web.seed       # опционально: заливает демо-данные в пустую БД
python -m sonya_web.cli --reload
```

Открыть [http://localhost:8000](http://localhost:8000). Подробнее — см.
[`sonya_web/README.md`](sonya_web/README.md).

---

## MVP-1: подключаем Telegram-аккаунт «Соня»

Чтобы перейти от «вхолостую» к реальному входу в Telegram:

1. Получи на https://my.telegram.org/apps бесплатные `api_id` и `api_hash` (форма выдаст после короткой анкеты).
2. Открой `.env` и впиши:
   ```
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef0123456789...
   TELEGRAM_PHONE=+7XXXXXXXXXX
   DRY_RUN=false
   ```
   `DRY_RUN=false` нужен чтобы Соня действительно отправляла ответы. С `DRY_RUN=true` входящие будут только логироваться и сохраняться в БД, без реальных отправок.
3. Запусти:
   ```powershell
   python -m sonya.main
   ```
4. **При первом запуске** Telegram пришлёт SMS-код на номер `TELEGRAM_PHONE`. Telethon попросит ввести код прямо в консоли — впиши и нажми Enter. Если на аккаунте включена 2FA — попросит ещё пароль.
5. После входа создастся файл `sonya.session` (он в `.gitignore` — хранит токен сессии). На следующих запусках SMS уже не нужен.
6. Должен увидеть:
   ```
   SUCCESS  Telegram client connected as: id=... username=@... name=...
   SUCCESS  Sonya is online. Listening for incoming PMs. Ctrl+C to stop.
   ```
7. С другого аккаунта напиши Соне в ЛС что-нибудь типа `hi`. Хендлер тонкий: каждое входящее идёт в `DialogueService` (см. ниже). Если LLM-ключ не задан — пришлёт заглушку `[stub] received: hi`. Если задан — ответит через выбранный LLM-провайдер.

---

## Подключаем LLM

Заменяем заглушку `[stub] received: ...` на реальные ответы Сони. Поддерживаем два бэкенда — выбор через `LLM_PROVIDER` в `.env`:

| `LLM_PROVIDER` | Что внутри | NSFW для OFM | Доп. ключи |
| --- | --- | --- | --- |
| `openai_compat` *(default)* | OpenAI-совместимый endpoint: OpenRouter, NVIDIA NIM, Groq, DeepSeek, Together, GitHub Models, OpenAI | ✅ через uncensored-модели (Hermes/Dolphin) | `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` |
| `gemini` | Google Gemini через нативный SDK `google-genai` | ⚠ жёсткий встроенный фильтр; для интим-сцен может не подойти | `GEMINI_API_KEY` + `GEMINI_MODEL` |

### Вариант B (подробно): Google Gemini

1. https://aistudio.google.com/app/apikey → `Create API key` → скопировать.
2. В `.env`:
   ```
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=AIza...
   GEMINI_MODEL=gemini-3-flash-preview
   ```
3. (Опц.) `GEMINI_THINKING_LEVEL=HIGH` включит «размышления» — модель думает дольше, ответ медленнее, но точнее. Для OFM-чата обычно не нужен.

В коде мы уже выкручиваем `safety_settings=OFF` для всех harm-категорий, чтобы дать Gemini максимально мягкую модерацию. Но **сама модель обучена отказывать** на явно сексуальный контент — увидишь в логах `prompt_feedback.block=SAFETY` или пустой ответ. В этом случае переключайся на uncensored через OpenRouter (вариант A ниже).

### Вариант A (default): любой OpenAI-совместимый провайдер

`LLM_PROVIDER=openai_compat` (или просто не указывай — это дефолт).

#### A.1: OpenRouter (рекомендуется как старт)

Один ключ → доступ к десяткам моделей (DeepSeek, Llama, Hermes, GLM, Mistral и т.д.). Есть `:free` модели.

1. https://openrouter.ai → Google login → https://openrouter.ai/keys → **Create Key** (`sk-or-v1-...`).
2. В `.env`:
   ```
   LLM_API_KEY=sk-or-v1-...твой ключ...
   LLM_BASE_URL=https://openrouter.ai/api/v1
   LLM_MODEL=nousresearch/hermes-3-llama-3.1-405b:free
   ```
   Это дефолт — Hermes 3 405B, uncensored, хорошо подходит для OFM.
   Альтернативы: `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen3-next-80b-a3b-instruct:free`, `cognitivecomputations/dolphin-mistral-24b-venice-edition:free`.
3. **Free tier:** 20 req/мин, 50/сутки при $0; 1000/сутки если положишь хотя бы $10.

#### A.2: NVIDIA NIM

5000 free кредитов на старте, лимит 40/мин.

1. https://build.nvidia.com → регистрация → верификация номера.
2. Любая модель → **Get API Key** (`nvapi-...`).
3. В `.env`:
   ```
   LLM_API_KEY=nvapi-...
   LLM_BASE_URL=https://integrate.api.nvidia.com/v1
   LLM_MODEL=deepseek-ai/deepseek-r1
   ```

#### A.3: Groq

Очень быстро, ~1000+/сутки бесплатно, но Llama-only (модель более «безопасная»).

1. https://console.groq.com/keys → **Create API Key** (`gsk_...`).
2. В `.env`:
   ```
   LLM_API_KEY=gsk_...
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_MODEL=llama-3.3-70b-versatile
   ```

#### A.4: DeepSeek API напрямую

$5 free на старте, затем копейки.

1. https://platform.deepseek.com → создать ключ (`sk-...`).
2. В `.env`:
   ```
   LLM_API_KEY=sk-...
   LLM_BASE_URL=https://api.deepseek.com
   LLM_MODEL=deepseek-chat
   ```

### Запуск и проверка

После того как ключ в `.env`:
```powershell
python -m sonya.main
```
В стартовом логе:
```
INFO  LLM backend ready (provider=<openai_compat|gemini>, model=<твоя модель>, endpoint=<...>, key=sk-or-v1…b35e57)
```
Напиши Соне в ЛС с другого аккаунта — должен прийти осмысленный ответ.

**Если LLM упал** (rate limit, нет интернета) — Соня отправит fallback-фразу `hey, give me a sec — back to you in a min 💕` и ошибка попадёт в лог. Без ключа вообще — она шлёт MVP-1 заглушку `[stub] received: <текст>`.

> **Старые `.env` с `OPENROUTER_API_KEY=...` тоже работают** — это back-compat алиас, ничего ломать не нужно.

---

## Workflow: я делаю PR — ты обновляешь у себя

1. Я (Devin) делаю изменения и открываю **Pull Request** в репозиторий `pvrmj88vmj-ops/AI-tg`.
2. Ты заходишь на GitHub, ревьюишь diff, нажимаешь **Merge pull request**.
3. У себя в VS Code:
   ```powershell
   git pull
   ```
   (или **Source Control → ⋯ → Pull**).
4. Если были новые зависимости — перепоставить:
   ```powershell
   pip install -r requirements.txt
   ```
5. Если были новые миграции — применить:
   ```powershell
   alembic upgrade head
   ```
6. Запустить:
   ```powershell
   python -m sonya.main
   ```

Если хочешь сам что-то поправить — обычный git: edit → `git commit -m "..."` → `git push`. На следующей сессии я подхвачу твои правки.

---

## Структура проекта

```
AI-tg/
├── sonya/
│   ├── main.py              # точка входа
│   ├── config.py            # pydantic-settings (читает .env)
│   ├── logging_setup.py     # loguru
│   ├── db/                  # SQLAlchemy: base, session, models
│   ├── telegram/            # Telethon-клиент           (MVP-1+)
│   ├── llm/                 # OpenAI-совместимый + Gemini backend, prompts
│   ├── dialogue/            # DialogueService — оркестратор одного хода
│   ├── runtime/             # per-fan lock, debounce, safe Telegram I/O
│   ├── safety/              # deterministic stop-rules (pre/post-LLM)
│   ├── knowledge/           # markdown loader + keyword retrieval
│   ├── crm/                 # client + facts repository
│   ├── humanizer.py         # typing/awareness задержки
│   └── playbooks/           # (план) intent → playbook selector
├── knowledge/               # обучающая база (read-only)
│   ├── ai_training/         # 35 файлов: персона, плейбуки, dialog examples
│   ├── content_catalog.md   # 47 контент-сетов
│   └── MEGA_HANDBOOK.md     # сводный handbook
├── migrations/              # Alembic
├── tests/                   # pytest
├── pyproject.toml
├── alembic.ini
└── .env.example
```

---

## БД: схема

7 таблиц, основанных на `knowledge/ai_training/18_memory_crm_playbook.md`:

| Таблица | Назначение |
|---|---|
| `clients` | Все фаны: тип (A1..G3), статус, расходы, грань голоса, флаги |
| `messages` | Полная история переписки с разметкой (используемая грань, плейбук) |
| `facts` | Известные факты о фане (имя, город, питомец, ДР, хобби...) |
| `content_sets` | 47 контент-сетов из каталога с ценой в Stars и таргетингом |
| `sales_attempts` | Попытки продаж: успешные / неуспешные / отклонённые |
| `followups` | Очередь cadence: ghost recovery, aftercare, ДР, ивенты |
| `events_log` | Технический аудит для отладки |

---

## Дорожная карта

| Фаза | Что | Статус |
|---|---|---|
| **0** Stabilization | README sync, healthcheck, smoke run, тесты на skeleton | ✅ Done |
| **1** Runtime safety MVP | per-fan lock, debounce, FloodWait/RPC backoff, structured event log | ✅ Done |
| **2** CRM memory MVP | facts repository (upsert/list), facts в client_card, prompt assembly | ✅ Done (basic; auto-extraction — нет) |
| **3** Knowledge MVP | markdown loader, in-memory keyword retrieval, prompt budget | ✅ Done (без embeddings) |
| **4** Dialogue orchestration | DialogueService, intent detection (deterministic), fan-type lite, bubble splitting, кооп. отмена humanizer | ✅ Done (MVP; LLM-based intent fallback и playbook selection — следующая итерация) |
| **5** Safety engine MVP | minors / non-consent / off-platform / crisis / AI-disclosure (pre+post) | ✅ Done (MVP) |
| **6** Sales / Telegram Stars | content_catalog parsing, recommend, invoice, payment lifecycle, delivery | ✅ Done |
| **7** Scheduler / cadence | APScheduler wiring, ghost recovery, aftercare | ✅ Done |
| **8** Admin / operator | pause/card/handoff/inspect-prompt через Telegram-чат | ✅ Done |
| **9** Deploy hardening | Dockerfile, compose, systemd, runbook | ✅ Done |
| **L1** CRM lifecycle fields | current_stage, risk_level, suppression, handoff, last_offer/last_purchase, events_log writer | ✅ Done |
| **L2** Safety engine v2 | structured `SafetyVerdict` (sales_allowed/proactive_allowed/suppression_hours), stop-request 72h, harassment / chargeback / intoxication | ✅ Done |
| **L3** Journey + Cadence + NextBestAction | stage-машина (welcome → warmup → qualify → offer_pending → aftercare → repeat_ready → ghost), three gates (offer / proactive / reply), `MIN_INBOUND_BEFORE_OFFER=5`, `OFFER_COOLDOWN=24h`, vulnerable-блок | ✅ Done |
| **L4** Structured LLM output | Pydantic-схема для ответов, валидация | ⏳ Отложено (free-tier модели плохо отдают JSON) |
| **L5** Followup hardening | auto-aftercare после успешного платежа, idempotent enqueue, pre-send cadence re-check, stop-request чистит очередь | ✅ Done |

### Известные ограничения текущего состояния

- **Fact extraction** не автоматическая. Чтобы Соня «помнила» имя/город/питомца — пока нужно вручную звать `upsert_fact` (или ждать L4 со structured LLM-извлечением). История сообщений сохраняется и подаётся в LLM-контекст в любом случае.
- **Knowledge retrieval** — keyword-overlap, без embeddings. Достаточно для ~150 chunks, для роста корпуса нужно будет переключить scorer.
- **Voice / image** входящие распознаются как media-type, но Соня отвечает текстом без транскрипции / vision.
- **Структурированный LLM-output** (L4) отложен. Free-tier модели нестабильно отдают JSON — пока интент классифицируется детерминистически, ответ — свободный текст с post-check'ом.
- **Auto-import каталога** (`knowledge/content_catalog.md` → таблица `content_sets`) пока ручной (`alembic upgrade head` + импорт-команда из admin-чата).

---

## Разработка

```powershell
# Линт
ruff check .

# Автоформат
ruff format .

# Тесты
pytest -q

# Создать новую миграцию (после правки моделей)
alembic revision --autogenerate -m "describe change"

# Применить миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1
```

---

## Безопасность

- `.env`, `*.session`, `*.db`, `logs/` — в `.gitignore`. Никогда не коммить.
- Все hard-rules из `knowledge/ai_training/06_AI_stop_list.md` зашиваются в код в `sonya/safety/` (MVP-8) — даже при правке промта они должны блокировать опасный вывод.
- Crisis-protocol (`15_crisis_safety_playbook.md`) — обязательный handoff на человека для уровней 3-4.
