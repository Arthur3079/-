"""Демо-данные для пустой БД, чтобы веб-панель сразу что-то показала.

Запуск::

    alembic upgrade head
    python -m sonya_web.seed

Безопасно вызывать повторно: вставляет только если в `clients` пусто.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from sonya.db.models import (
    Client,
    ContentSet,
    EventLog,
    Fact,
    FanStatus,
    Followup,
    Message,
    MessageDirection,
    MessageMediaType,
    PaymentEvent,
    SaleOutcome,
    SalesAttempt,
    SalesStatus,
)
from sonya.db.session import async_session_factory
from sonya.journey.stages import RiskLevel, Stage

SAMPLE_FANS = [
    ("alex_b", "Alex", "B1", Stage.QUALIFY, RiskLevel.NONE, 12.0, 1),
    ("max_payer", "Max", "C2", Stage.AFTERCARE, RiskLevel.NONE, 88.0, 4),
    ("lonely_d", "Daniel", "D1", Stage.WARMUP, RiskLevel.LOW, 0.0, 0),
    ("ghost_e", "Eric", "E2", Stage.GHOST, RiskLevel.NONE, 4.0, 1),
    ("whale_f", "Frank", "F3", Stage.REPEAT_READY, RiskLevel.NONE, 412.0, 12),
    ("rude_g", "George", "G1", Stage.HANDOFF, RiskLevel.HIGH, 0.0, 0),
    ("welcome_h", "Henry", None, Stage.WELCOME, RiskLevel.NONE, 0.0, 0),
    ("offer_i", "Ivan", "B2", Stage.OFFER_PENDING, RiskLevel.NONE, 18.0, 1),
]

SAMPLE_INBOUND = [
    "hey",
    "what are you up to?",
    "send me something cute",
    "you online babe?",
    "miss you",
    "lol",
    "tell me about yourself",
    "you live in moscow?",
]

SAMPLE_OUTBOUND = [
    "heyy 🌸 just woke up, you?",
    "haha you're sweet",
    "i was thinking about you actually",
    "wanna see something special I made today? 💋",
    "how was your day, baby",
    "tell me one thing that made you smile today",
]

SAFETY_EVENTS = [
    ("safety_flagged", {"rule": "off_platform_pressure", "severity": "low"}),
    ("safety_reply_blocked", {"rule": "intoxication", "severity": "medium"}),
    ("suppression_applied", {"hours": 24, "reason": "minor_doubt"}),
    ("handoff_required", {"trigger": "crisis_keyword"}),
]

SAMPLE_CONTENT_SETS = [
    ("T1-warmup", "Warmup pack", "warmup", 4.99),
    ("T2-disco", "Disco set", "glam", 9.99),
    ("T3-cute", "Cute morning", "casual", 6.99),
    ("T4-spicy", "Spicy night", "spicy", 14.99),
    ("T5-bts", "Behind the scenes", "bts", 19.99),
    ("T6-mega", "Mega bundle", "bundle", 39.99),
]


async def seed() -> None:
    factory = async_session_factory()
    async with factory() as session:
        existing = (await session.execute(select(func.count(Client.fan_id)))).scalar_one() or 0
        if existing:
            print(f"DB already has {existing} clients — пропускаю seed.")
            return

        now = datetime.now(UTC)
        rng = random.Random(42)
        window_max_days = 14

        # Заполним пустой каталог контента, если он ещё не существует.
        catalog_count = (await session.execute(select(func.count(ContentSet.id)))).scalar_one() or 0
        catalog_ids: list[int] = []
        if not catalog_count:
            for code, name_, theme, price in SAMPLE_CONTENT_SETS:
                cs = ContentSet(
                    code=code,
                    name=name_,
                    theme=theme,
                    price_stars=int(price * 100),
                    price_usd_equivalent=price,
                    is_active=True,
                )
                session.add(cs)
                await session.flush()
                catalog_ids.append(cs.id)
        else:
            catalog_ids = [
                row[0] for row in (await session.execute(select(ContentSet.id).limit(20))).all()
            ]

        for idx, (uname, name, ftype, stage, risk, spend, purchases) in enumerate(SAMPLE_FANS):
            fan_id = 100_000 + idx
            first_seen = now - timedelta(days=rng.randint(2, 30))
            last_active = now - timedelta(hours=rng.randint(0, 72))
            client = Client(
                fan_id=fan_id,
                username=uname,
                first_name=name,
                display_name=name,
                fan_type=ftype,
                type_confidence="high" if ftype else None,
                status=FanStatus.GHOST if stage == Stage.GHOST else FanStatus.ACTIVE,
                language="en",
                country_guess=rng.choice(["US", "UK", "DE", "RU", "CA"]),
                first_seen=first_seen,
                last_active=last_active,
                last_inbound_at=last_active,
                last_outbound_at=last_active - timedelta(minutes=rng.randint(1, 120)),
                total_spend_30d=min(spend, 200.0),
                total_spend_lifetime=spend,
                ltv_estimate=spend * 1.4,
                preferred_grain=rng.choice(["G3", "G6", "G9", None]),
                sales_status=SalesStatus.ACTIVE,
                flags=None,
                notes=None,
                is_paused=False,
                paused_reason=None,
                current_stage=stage.value,
                risk_level=risk.value,
                consecutive_outbound_without_reply=0 if stage != Stage.GHOST else rng.randint(2, 5),
                last_offer_at=last_active - timedelta(hours=rng.randint(2, 48))
                if purchases
                else None,
                last_purchase_at=last_active - timedelta(days=rng.randint(1, 14))
                if purchases
                else None,
                handoff_required=stage == Stage.HANDOFF,
            )
            session.add(client)
            await session.flush()

            # Факты
            sample_facts = [
                ("name", name or "?"),
                ("city", rng.choice(["NYC", "LA", "Berlin", "Moscow", "Toronto"])),
                ("job", rng.choice(["dev", "designer", "trader", "barista"])),
                ("hobby", rng.choice(["gym", "gaming", "cooking", "running"])),
            ]
            for k, v in sample_facts:
                session.add(
                    Fact(
                        fan_id=fan_id,
                        key=k,
                        value=v,
                        confidence="mid",
                        date_disclosed=first_seen + timedelta(hours=rng.randint(1, 48)),
                    )
                )

            # Сообщения — раскидаем по последним 7 дням
            n_msgs = rng.randint(20, 60)
            for j in range(n_msgs):
                # spread evenly across last 7 days with random jitter
                day_offset = (j / max(n_msgs - 1, 1)) * 6.5
                jitter_minutes = rng.randint(-180, 180)
                ts = now - timedelta(days=6.5 - day_offset, minutes=jitter_minutes)
                if ts > now:
                    ts = now
                if j % 2 == 0:
                    session.add(
                        Message(
                            fan_id=fan_id,
                            direction=MessageDirection.INCOMING,
                            media_type=MessageMediaType.TEXT,
                            content=rng.choice(SAMPLE_INBOUND),
                            timestamp=ts,
                        )
                    )
                else:
                    session.add(
                        Message(
                            fan_id=fan_id,
                            direction=MessageDirection.OUTGOING,
                            media_type=MessageMediaType.TEXT,
                            content=rng.choice(SAMPLE_OUTBOUND),
                            timestamp=ts,
                            used_grain=rng.choice(["G3", "G6", "G9"]),
                            used_playbook=rng.choice(
                                ["welcome_flow", "warmup", "ppv_sales", "aftercare"]
                            ),
                        )
                    )

            # Покупки + payment events + неудачные попытки для воронки
            for p_idx in range(purchases):
                attempted_at = now - timedelta(
                    days=rng.randint(0, max(1, min(window_max_days, 14))),
                    hours=rng.randint(0, 23),
                )
                amount = round(rng.uniform(5, 60), 2)
                content_set_id = catalog_ids[p_idx % len(catalog_ids)] if catalog_ids else None
                attempt = SalesAttempt(
                    fan_id=fan_id,
                    content_set_id=content_set_id,
                    attempted_at=attempted_at,
                    outcome=SaleOutcome.PURCHASED,
                    amount_stars=int(amount * 100),
                    amount_usd_equivalent=amount,
                    invoice_payload=f"inv-{fan_id}-{int(attempted_at.timestamp())}",
                    grain_used=rng.choice(["G3", "G6", "G9"]),
                    message_text="here you go babe",
                )
                session.add(attempt)
                await session.flush()
                session.add(
                    PaymentEvent(
                        fan_id=fan_id,
                        sales_attempt_id=attempt.id,
                        event_type="successful",
                        amount_stars=attempt.amount_stars,
                        currency="XTR",
                        invoice_payload=attempt.invoice_payload,
                        telegram_charge_id=f"chrg_{fan_id}_{p_idx}",
                        timestamp=attempted_at + timedelta(seconds=5),
                    )
                )
            # Несколько ignored / declined для воронки
            for _ in range(rng.randint(0, 2)):
                attempted_at = now - timedelta(days=rng.randint(0, 14), hours=rng.randint(0, 23))
                session.add(
                    SalesAttempt(
                        fan_id=fan_id,
                        attempted_at=attempted_at,
                        outcome=rng.choice([SaleOutcome.IGNORED, SaleOutcome.DECLINED]),
                        amount_stars=0,
                        amount_usd_equivalent=0.0,
                        grain_used=rng.choice(["G3", "G6", "G9"]),
                        message_text="want to see something special?",
                    )
                )

            # Followups
            if stage in {Stage.GHOST, Stage.REPEAT_READY, Stage.AFTERCARE}:
                session.add(
                    Followup(
                        fan_id=fan_id,
                        type=rng.choice(["ghost_d3", "aftercare_24h", "repeat_offer"]),
                        scheduled_at=now + timedelta(hours=rng.randint(1, 48)),
                        note="auto-generated",
                    )
                )

        # Несколько safety events за последние 7 дней
        for _ in range(20):
            event_type, payload = rng.choice(SAFETY_EVENTS)
            session.add(
                EventLog(
                    fan_id=100_000 + rng.randrange(len(SAMPLE_FANS)),
                    event_type=event_type,
                    payload=json.dumps(payload),
                    timestamp=now - timedelta(days=rng.randint(0, 6), hours=rng.randint(0, 23)),
                )
            )

        await session.commit()
        print("Seed complete.")


def _cli() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    _cli()
