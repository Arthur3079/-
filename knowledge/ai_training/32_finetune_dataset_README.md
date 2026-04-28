# 32. Fine-tune Dataset — `32_finetune_dataset.jsonl`

> Готовый JSON Lines датасет для fine-tune Sonya OFM AI на собственных
> примерах. **79 примеров (69 good + 10 bad)** покрывают все 30 типов
> фанов и ключевые сценарии.

---

## Файлы

| Файл | Описание |
|---|---|
| `32_finetune_dataset.jsonl` | 79 примеров в JSONL формате |
| `32_finetune_dataset_README.md` | Этот файл |
| `_generate_finetune_dataset.py` | Генератор (можно расширять и пересобирать) |

---

## Формат записи

Каждая строка `.jsonl` — это один JSON объект:

```json
{
  "messages": [
    {"role": "system", "content": "<persona reminder>"},
    {"role": "user", "content": "<context tag + fan message>"},
    {"role": "assistant", "content": "<Sonya reply>"}
  ],
  "metadata": {
    "fan_type": "B1",
    "grain_stack": ["G6", "G9"],
    "scenario": "whale tip after voice",
    "source_file": "26_dialogue_examples_A_B.md",
    "tags": ["whale", "tip", "aftercare"],
    "label": "good",
    "language": "ru",
    "version": "v1"
  }
}
```

### Поля

**`messages`** — стандартный chat-format для SFT:
- `system` — короткая persona-напоминалка (главный prompt — `08_AI_master_prompt.md`)
- `user` — реплика фана **с контекстным тегом** в первой строке:
  - формат: `[fan_type=B1, name=James, lifetime=$4200, dog=Bear]`
  - после пустой строки — собственно `fan: <message>`
- `assistant` — целевой ответ Сони

**`metadata`** — для фильтрации, оценки и стратификации:
- `fan_type` — A1-G3 (по 30-type matrix из `03`)
- `grain_stack` — какие грани (G1-G12) активны (по `02`)
- `scenario` — короткое описание ситуации
- `source_file` — из какого файла извлечено
- `tags` — для поиска / фильтрации
- `label` — `"good"` или `"bad"`
- `language` — `"ru"`, `"en"`, или `"mixed"`

### `bad` примеры (label="bad")

10 negative samples с `bad_reasons[]` — список конкретных нарушений
(stop-list, false promise, push в vulnerable, и т.д.). Используются для:

- DPO (Direct Preference Optimization) — pair good vs bad с одинаковым `user` сообщением
- Contrastive learning
- Negative training signal

Pairs (good vs bad по тому же fan-message):

| User message | Good | Bad |
|---|---|---|
| A1 «hey» | warm + match tempo | bio dump + PPV push |
| B1 whale tip + thank | grateful restrained | greedy push «more please» |
| B1 «do you actually care» | honest warm boundary | false «would do anything» |
| C7a lonely tonight | listening + no PPV | PPV pivot + «forever» |
| C7c suicide ideation | helpline level 3 template | sales pivot in crisis |
| E4 sextortion | «не отвечаю на угрозы» | begging + discount offer |
| D2 sexting trigger | warmup phase 2 | premature peak with cliche |
| E3 discount $10 | tier alternative | discount given |
| D6 age-play | clear hard-stop redirect | joke quote $500 |
| C3 «I love you» | warm acknowledge | «I love you back forever» |

---

## Распределение по типам фанов

```
A1  4    B1  8    C1  2    D1  3    E1  1    F1  1    G1  2
A2  2    B2  2    C2  1    D2  4    E2  2    F2  1    G2  1
A3  3    B3  1    C3  5    D3  1    E3  2    F3  1    G3  3
A4  1    B4  1    C4  2    D4  1    E4  2    F4  1
A5  2    B5  1    C5  1    D5  1                       cross 3
                  C6  1    D6  3
                  C7a 4
                  C7b 3
                  C7c 2

Total: 79 (69 good + 10 bad)
```

Whale (B1) и vulnerable (C3, C7) overweight — это намеренно: эти типы
имеют наивысший impact на retention и safety.

---

## Использование для fine-tune

### OpenAI fine-tune

```bash
# Удалить metadata перед загрузкой (OpenAI не принимает extra fields)
jq -c '{messages}' 32_finetune_dataset.jsonl > openai_train.jsonl

# Загрузить
openai api files.create -f openai_train.jsonl -p fine-tune

# Запустить fine-tune
openai api fine_tuning.jobs.create \
  --training-file <file_id> \
  --model gpt-4o-mini \
  --suffix "sonya-v1"
```

### Anthropic / Claude

Anthropic не предлагает классический fine-tune для опубликованных
моделей, но датасет можно использовать в:
- Few-shot prompting (добавить 5-10 examples в system prompt)
- Custom evaluation rubric
- Constitutional AI feedback signal

### HuggingFace SFT (Trainer / TRL)

```python
from datasets import load_dataset
ds = load_dataset("json", data_files="32_finetune_dataset.jsonl")

# Filter only good samples for SFT
sft = ds.filter(lambda x: x["metadata"]["label"] == "good")

# For DPO (pair good with bad on same user message)
# нужна дополнительная подготовка — pair matching by user content hash
```

### vLLM / open-source models

Для Llama-3, Qwen, Mistral fine-tune через LoRA / QLoRA:
- Конвертировать JSONL в прямой ChatML формат
- Использовать `axolotl` или `unsloth` с config `chat_template: chatml`

---

## Расширение датасета

Добавлять новые примеры через `_generate_finetune_dataset.py`:

1. Открыть `_generate_finetune_dataset.py`
2. Добавить новый `records.append(entry(...))` блок с правильным
   контекстом, типом, scenario, tags
3. Запустить `python3 _generate_finetune_dataset.py`
4. Проверить distribution в выводе — если есть underweight типы,
   добавить ещё

Идеи для расширения:
- A/B варианты из `30_edge_cases_AB_variants.md` (12 кейсов × 3 варианта = 36 examples)
- Все good vs bad pairs из `31` как paired data для DPO (~30 pairs)
- Конкретные tier transitions (B2 → B1 whale ladder)
- Multi-turn examples (расширить messages list 5-10 turns)
- Voice / custom delivery scenarios
- Holiday-specific (Valentine, Christmas, ДР) с pre-warm chains

**Целевой объём для production fine-tune:** 300-500 good examples
+ 50-100 bad examples + 50-100 multi-turn dialogues.

---

## Чек перед использованием

Перед использованием датасета для production fine-tune:

- [ ] Проверить что **system prompt в записях соответствует** актуальному
  `08_AI_master_prompt.md` (или обновить через `_generate_finetune_dataset.py`)
- [ ] Удалить любые real PII (если в будущем добавите примеры из
  реальных переписок — анонимизировать имена, даты, города,
  компании)
- [ ] Подтвердить что все `bad` примеры **четко помечены** и не
  попадут в обучающий subset как positive
- [ ] Проверить language coverage (RU vs EN баланс под целевую
  аудиторию)
- [ ] Проверить tag coverage — нет ли overweight на одной категории
- [ ] Запустить sample inference после fine-tune на 12-question
  pre-send checklist (`24_pre_send_checklist.md`)

---

## Validation set предложение

Из 79 примеров отделить ~15-20% (12-16 records) как **validation**:
- Stratify по `fan_type` чтобы все типы были представлены в обоих
  splits
- Stratify по `label` — good и bad оба в validation
- Особо включить C7c, E4, D6 hard-stop в validation (CRITICAL safety
  cases)

---

## Метрики после fine-tune

Использовать `07_AI_metrics_calibration.md` метрики:

- **Stop-list violations:** 0% target на validation
- **Tempo match:** ±20% длины message vs target
- **Memory recall accuracy:** правильное использование context tag
- **Tier discipline:** 0% discount given, 0% wrong-tier anchors
- **Crisis safety:** 100% helpline template для C7c / E4 cases
- **Tone authenticity:** human reviewer rating 1-5, target ≥4.5

Запускать на 50+ test prompts перед deploy.
