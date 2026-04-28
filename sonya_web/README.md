# Sonya Admin (web)

Минимальная локальная веб-панель для наблюдения и управления Sonya.

**Что показывает:**

- **Дашборд** — KPI (активные/новые фаны, сообщения in/out, response rate,
  revenue, conversion, safety blocks, whales) + график активности и
  revenue + воронка по journey-стадиям.
- **Фаны** — список с фильтрами по стадии, карточка с фактами, флагами,
  историей сообщений.
- **Safety** — счётчики по типам событий + лента safety/handoff/suppression.
- **Scheduler** — очередь proactive-followups на ближайшие 72 часа.
- **Live** — SSE-канал, который тянет новые строки из `events_log` и
  показывает их в реальном времени на дашборде.

## Запуск

```bash
pip install -e ".[web]"
alembic upgrade head
python -m sonya_web.seed                 # опционально: 8 демо-фанов с историей
python -m sonya_web.cli --reload         # uvicorn, http://localhost:8000
```

Альтернативно — через `uvicorn` напрямую:

```bash
uvicorn sonya_web.app:app --reload --port 8000
```

## Архитектура

- **Backend:** FastAPI поверх существующих моделей `sonya.db.models`,
  `sonya.kpi.metrics`, `sonya.crm.*`. Никакого дублирования бизнес-логики.
- **Frontend:** одна `static/index.html` + `app.js` + `styles.css` без
  npm/билда. Tailwind, Chart.js, Alpine.js подключены через CDN.
- **Real-time:** `/api/events/stream` — SSE с polling-loop по `events_log`
  (раз в 2 секунды). Достаточно для локального инстанса.
- **Auth:** **нет**. Это локальная панель, не выставлять наружу.

## API

| Метод | Endpoint                                      | Описание                            |
| ----- | --------------------------------------------- | ----------------------------------- |
| GET   | `/api/dashboard/summary?window_days=7`        | KPI за окно                         |
| GET   | `/api/dashboard/activity?window_days=7`       | Сообщения/revenue/new fans по дням  |
| GET   | `/api/funnel`                                 | Воронка по journey-стадиям          |
| GET   | `/api/clients?stage=&status=&limit=&offset=`  | Список фанов                        |
| GET   | `/api/clients/{fan_id}`                       | Карточка: профиль + facts           |
| GET   | `/api/clients/{fan_id}/messages?limit=`       | История сообщений                   |
| GET   | `/api/safety/events?limit=`                   | Лента safety-событий                |
| GET   | `/api/safety/summary?window_days=`            | Счётчики по типам                   |
| GET   | `/api/scheduler/upcoming?horizon_hours=`      | Предстоящие followups               |
| GET   | `/api/events/stream`                          | SSE-канал из `events_log`           |

OpenAPI / Swagger UI доступен на `/docs`.

## Дальше (TODO)

- Действия оператора (`pause`, `handoff`, `note`) — POST-эндпоинты + кнопки.
- LLM-дамп: для каждого исходящего сообщения показывать промпт/latency.
- Sales tab: попытки продаж, payment events, content deliveries.
- Вынести polling SSE в pub/sub шину при подключении к живому runtime.
- Telegram-Login / allowlist для прод-деплоя.
