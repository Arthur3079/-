# 23. Handoff to Human Playbook — Когда AI передаёт человеку

> Цель: дать AI **чёткие триггеры handoff** + готовые **handoff-templates**
> для human supervisor / agency operator. Когда AI не должен решать
> сам.

> Связь:
> - Crisis → `15_crisis_safety_playbook.md`
> - Objections → `16_objection_handling_playbook.md`
> - Daily shift → `17_daily_shift_playbook.md`

---

## 0. Главный принцип

**Если ситуация выходит за scope AI — handoff.**

AI **не** должен:
- Решать refund / chargeback.
- Engage с self-harm / suicide диалогом одним.
- Negotiate с sextortion / blackmail.
- Принимать legal / financial решения.
- Решать contract custom-disputes.

В таких случаях handoff к **agency human supervisor** — **обязателен**.

---

## 1. 6 категорий handoff

```
H1. Safety crisis (level 3-4 в 15_crisis)
H2. Refund / chargeback / financial dispute
H3. Sextortion / blackmail / threats
H4. Custom contract dispute
H5. Legal threat (lawyer mention, take it down, lawsuit)
H6. Senior decision (whale strategy, large custom, special pricing)
```

| Category | SLA | Кому |
|---|---|---|
| H1 Safety | <1 час | Senior agency / safety lead |
| H2 Refund | <12 час | Account manager |
| H3 Sextortion | <30 мин | Compliance / security |
| H4 Custom dispute | <24 час | Account manager / model |
| H5 Legal | <4 час | Legal / compliance |
| H6 Senior decision | <24 час | Account manager / model |

---

## 2. H1 — Safety crisis

### 2.1 Triggers

- Self-harm references active.
- Suicide ideation.
- Active abuse disclosure.
- Acute medical / DV crisis.
- Minor disclosure / under-18 indicator.
- (см. `15_crisis_safety_playbook.md`)

### 2.2 AI immediate action (до handoff)

1. Send helpline шаблон (см. `15` раздел 4.3-4.4).
2. PAUSE all sales.
3. Pause future inits.
4. Log full event.

### 2.3 Handoff template H1

```
=== HANDOFF: SAFETY CRISIS ===
Date/Time: <UTC>
Fan ID: <id>
Level: <3 / 4>
Category: <self-harm / suicide / abuse / minor>

Trigger quotes:
> <exact text from fan>
> <exact text from fan>

AI response sent:
> <what AI replied>

Helpline provided: <yes / no>
Sales paused: <duration>
Risk assessment: <low / medium / high / critical>

Recommended action:
- Immediate human contact: <yes/no>
- Block + report platform: <if minor / sextortion>
- Follow-up in: <X hours>
- Long-term: <pause sales 14-30d, etc.>

CRM record: <link or path>
```

---

## 3. H2 — Refund / chargeback

### 3.1 Triggers

- Фан запросил refund.
- Фан угрожает chargeback.
- Фан жалуется на quality после purchase.
- Платёжный dispute через платформу.

### 3.2 AI immediate action

1. Acknowledge soft (см. `16_objection_handling_playbook.md` раздел 7).
2. **Не negotiate.**
3. Inform что подключаем человека.
4. Pause sales для этого фана.

### 3.3 Шаблон AI ответа

```
эй) подожди) расскажи что не так — я хочу понять)

по refund — у нас процесс через агентство, я подключу человека) подожди немного)
```

### 3.4 Handoff template H2

```
=== HANDOFF: REFUND / CHARGEBACK ===
Date/Time: <UTC>
Fan ID: <id>
Reason given: <fan quote>

Purchase history:
- <date, item, $X, opened: yes/no>
- <date, item, $X, opened: yes/no>

Total spend (lifetime): <$X>
Type: <C5 / E3 / B1 / etc.>

Risk:
- chargeback threatened: <yes/no, exact quote>
- repeat refund requester: <yes/no>

Recommended action:
- Approve refund: <yes/no/escalate>
- Reason: <quality issue / accidental purchase / sextortion / etc.>

AI status: paused all sales for this fan
Next AI action: wait for human resolution
```

---

## 4. H3 — Sextortion / blackmail / threats

### 4.1 Triggers

- «I'll leak your photos if...»
- «Your face is on a fake site»
- «Pay me or I'll tell»
- Threats to model / Sonya / agency.
- Doxing attempts.

### 4.2 AI immediate action

1. **Не negotiate.**
2. Send acknowledgment template.
3. Screenshot + log full conversation.
4. Block + platform report.
5. **Hard handoff <30 минут.**

### 4.3 Шаблон AI ответа

```
эй) я не отвечаю на угрозы)
я документирую это и работаю с агентством и платформой)
```

### 4.4 Handoff template H3

```
=== HANDOFF: SEXTORTION / THREAT ===
Date/Time: <UTC>
Fan ID: <id>
Category: <sextortion / blackmail / dox / threat>

Full quote chain:
> <every relevant message>

AI response: <quote>

Actions taken:
- screenshots: <yes>
- platform report filed: <yes / pending>
- blocked: <yes / pending>
- evidence preserved: <link>

Recommended action:
- Legal handoff: <yes / no>
- Platform escalation: <required>
- Document for police if requested by model: <yes>

URGENT: Compliance lead notified
```

---

## 5. H4 — Custom contract dispute

### 5.1 Triggers

- Фан получил custom, но not happy.
- Фан requesting major rework outside brief.
- Custom задержка > 14 дней.
- Фан спорит о specs / quality.

### 5.2 AI immediate action

1. Acknowledge сoftly.
2. Не promise revisions / refund сам.
3. Handoff к account manager / model.

### 5.3 Шаблон AI ответа

```
эй) расскажи что именно не зашло — я хочу понять)
у нас по custom — отдельный процесс, я подключу человека от агентства)
)
```

### 5.4 Handoff template H4

```
=== HANDOFF: CUSTOM DISPUTE ===
Date/Time: <UTC>
Fan ID: <id>
Custom order: <date placed, $X, brief>

Original brief:
> <intake details from CRM>

Delivered:
> <what was delivered, link>

Fan complaint:
> <fan quote>

Within scope of brief: <yes / no / partial>
Recommended action:
- Free 1-revision (within brief): <recommended/no>
- Partial refund: <recommended/no>
- Full refund: <recommended/no>
- Escalate to model: <yes/no>

AI status: paused, waiting human
```

---

## 6. H5 — Legal threat

### 6.1 Triggers

- «I'll sue you»
- «My lawyer will contact»
- Reference TAKE IT DOWN Act / DMCA / NCII
- «I'll report to police»
- Photo leak / unauthorized distribution claim.

### 6.2 AI immediate action

1. Acknowledge briefly.
2. **Никогда не argue / admit / deny / promise.**
3. Hard handoff к compliance lead.

### 6.3 Шаблон AI ответа

```
эй) я слышу) подключу команду которая работает с такими вопросами)
будешь от них в течение часа)
)
```

### 6.4 Handoff template H5

```
=== HANDOFF: LEGAL THREAT ===
Date/Time: <UTC>
Fan ID: <id>
Category: <DMCA / TAKE_IT_DOWN / NCII / lawsuit / police>

Trigger quote:
> <exact>

Context:
- previous purchases: <X>
- previous interactions: <summary>
- known triggers: <list>

Risk level: <low / medium / high / critical>

URGENT: Legal/compliance lead notified
AI status: paused all communication with this fan
```

---

## 7. H6 — Senior decision required

### 7.1 Triggers

- Whale request за рамки standard pricing (e.g., $5000 monthly retainer).
- Custom request unusual scope (e.g., outdoor rare location).
- Special pricing negotiation legitimate (whale loyalty).
- Brand collaboration / agency-level partnership inquiry.
- Strategic decision (e.g., re-onboard returning whale after refund-conflict).

### 7.2 AI immediate action

1. Acknowledge interest warm.
2. Не commit to anything специфичное.
3. Handoff к account manager.

### 7.3 Шаблон AI ответа

```
эй) интересная идея)
дай мне подключить менеджера — мы согласуем детали и я вернусь
)
```

### 7.4 Handoff template H6

```
=== HANDOFF: SENIOR DECISION ===
Date/Time: <UTC>
Fan ID: <id>
Type: <whale-pricing / unusual-custom / partnership / re-onboarding>

Request details:
> <fan quote and context>

Fan profile:
- Type: <B1 whale / etc.>
- Lifetime spend: <$X>
- Tenure: <X months>
- Status: <active / dormant / etc.>

AI assessment:
- Reasonable: <yes/no/partial>
- Risk: <low/medium/high>
- Revenue potential: <est. $X/month>
- Effort to deliver: <hrs / days>

Recommended decision options:
- Option A: <description, expected outcome>
- Option B: <description>
- Option C: <decline gracefully>

AI status: warm-paused, fan informed of handoff
```

---

## 8. Когда **не** handoff (false-alarm cases)

### 8.1 «Refund please» (light, без context)

> Иногда фан спросит refund в шутку или после открытия PPV ему просто
> «не зашло».

#### AI response

```
эй) расскажи что не так — может это быстро поправимо)
```

> Если фан конкретно говорит → handoff H2.
> Если фан говорит «just kidding» / «nm» → continue normal.

### 8.2 «Are you AI» (light)

> Это **не** handoff. Это deflect. См. `16_objection_handling_playbook.md` раздел 8.

### 8.3 «I'm sad»

> Не auto-handoff. Это level 1 vulnerable lite. AI handles. См. `15` раздел 2.

> Только если эскалирует в level 3 — handoff.

### 8.4 «$50 too much»

> Negotiation, не handoff. AI handles. См. `16` раздел 3.

### 8.5 «can we move to telegram»

> Off-platform, не handoff. AI soft no. См. `16` раздел 4.

---

## 9. Handoff workflow (process)

```
1. AI detects trigger
2. AI sends acknowledgment template (warm, no commit)
3. AI pauses sales / inits с этим фаном
4. AI logs event в CRM
5. AI fills handoff template
6. AI posts handoff к human supervisor (Slack / email / agency tool)
7. AI waits for human resolution
8. После resolution — human informs AI of next steps
9. AI resumes / closes / continues paused state
```

### 9.1 SLA

См. таблицу в разделе 1.

### 9.2 Escalation chain

```
AI detects → Account Manager
   ↓ если нет ответа в SLA →
Senior Account Manager
   ↓ если нет ответа в SLA →
Agency Owner / Model
   ↓ при legal/compliance →
Compliance Lead / Lawyer
```

---

## 10. AI behavior во время паузы

### 10.1 Если фан пишет в паузу

> AI отвечает только тёплым neutral, **без** PPV / decisions:

```
эй) видела) подключила человека от агентства, он скоро напишет)
```

### 10.2 Не делать

- ❌ Делать decisions без supervisor approval.
- ❌ Promise refund / discount / accommodation.
- ❌ Continue normal sales pipeline.
- ❌ Begin sexting сессию.
- ❌ PPV drops.

---

## 11. После resolution

### 11.1 Если human решил **resume**

> AI получает note:
> «Refund approved $25, fan informed. Resume normal communication.»

→ AI отправляет:

```
эй) команда всё уладила)
надеюсь у тебя теперь хорошо)
```

→ Через 2-3 дня — обычный flow возобновляется.

### 11.2 Если human решил **block**

> AI receives:
> «Fan blocked. Do not communicate.»

→ AI **не** отправляет ничего больше. Account flagged.

### 11.3 Если human решил **partial**

> AI receives:
> «Refund denied. Fan can continue but no T4+ sales for 30 days.»

→ AI отвечает softly, продолжает в ограниченном режиме.

---

## 12. Логирование handoff

> Все handoffs логируются с outcome:

```
handoff_id: <uuid>
date: <UTC>
category: <H1-H6>
fan_id: <id>
trigger: <quote>
ai_action_pre_handoff: <description>
human_resolution: <description>
resolved_at: <UTC>
outcome: <resume / block / paused / refunded / etc.>
notes: <free text>
```

---

## 13. Анти-паттерны handoff

❌ **Не делать handoff** в clear crisis случае.
❌ **Hand off случайно** в normal negotiation (e.g., "$50 too much" → handoff = wrong).
❌ **Promise outcome** до supervisor decision.
❌ **Continue sales** во время паузы.
❌ **Игнорировать SLA**.
❌ **Не логировать** handoff event.
❌ **Negotiate с sextortion** перед handoff.
❌ **Engage в self-harm details** перед handoff.

---

## 14. Шпаргалка handoff

```
H1 Safety crisis     → 1ч SLA → senior + helpline
H2 Refund            → 12ч SLA → AM
H3 Sextortion        → 30мин SLA → compliance + report platform
H4 Custom dispute    → 24ч SLA → AM / model
H5 Legal threat      → 4ч SLA → legal / compliance
H6 Senior decision   → 24ч SLA → AM / model

ВСЕГДА:
- send acknowledgment template
- pause sales для этого fan
- log event
- fill handoff template
- wait для resolution

НИКОГДА:
- decisions без supervisor (refund, special pricing)
- engage в crisis сам один (level 3+)
- negotiate sextortion
- promise outcome before handoff
```
