# PASH Price Bot — Техническое задание

## Контекст

Telegram-бот для мониторинга цен на фрукты и овощи.
Используется основателем PASH (и опционально продавцами на Алтын-Орде).
Данные пишутся в Supabase и отображаются во внутреннем дашборде.

---

## Стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.11+ |
| Telegram | `python-telegram-bot` v21 (async) |
| Транскрипция голоса | Gemini 2.0 Flash (аудио нативно, без конвертации) |
| Парсинг текста | Gemini 2.0 Flash + `response_schema` |
| Распознавание фото | Gemini 2.0 Flash (vision встроен) |
| База данных | Supabase (REST API через `supabase-py`) |
| Деплой | Railway или Fly.io (один контейнер) |
| Конфиг | `.env` файл |

**Один SDK для всего AI:** `google-generativeai`. Один API key. Голос, текст, фото — один и тот же клиент, разные промпты.

---

## Переменные окружения (.env)

```
TELEGRAM_BOT_TOKEN=
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_ANON_KEY=
ALLOWED_USER_IDS=123456789,987654321   # telegram user_id через запятую
```

API key берётся из Google AI Studio: https://aistudio.google.com/apikey

---

## Схема базы данных Supabase

### Таблица `products`
```sql
create table products (
  id serial primary key,
  name text not null,           -- "банан"
  name_aliases text[],          -- ["бананы", "banana"]
  unit text not null,           -- "кг" | "шт"
  category text,                -- "hook" | "margin"
  our_price numeric,            -- текущая цена PASH
  created_at timestamptz default now()
);
```

### Таблица `price_snapshots`
```sql
create table price_snapshots (
  id bigserial primary key,
  product_id int references products(id),
  source text not null,         -- "magnum" | "treds" | "galmart" | "arbuz" | "lavka" | "altyn_orda"
  price numeric not null,
  unit text,                    -- если отличается от products.unit
  raw_input text,               -- оригинальный текст/описание для аудита
  recorded_at timestamptz default now()
);
```

### Таблица `alerts`
```sql
create table alerts (
  id bigserial primary key,
  product_id int references products(id),
  type text,                    -- "gap_shrink" | "price_drop" | "price_spike"
  message text,
  seen boolean default false,
  created_at timestamptz default now()
);
```

---

## Структура проекта

```
pash-price-bot/
├── main.py              # точка входа, регистрация handlers
├── handlers/
│   ├── voice.py         # обработка голосовых сообщений
│   ├── photo.py         # обработка фото/скриншотов
│   ├── text.py          # текстовые команды
│   └── confirm.py       # обработка подтверждений (инлайн-кнопки)
├── services/
│   ├── gemini.py        # единый клиент Gemini: голос, текст, фото
│   ├── supabase.py      # запись/чтение из БД
│   └── alerts.py        # проверка и генерация алертов
├── models.py            # dataclasses: PriceEntry, ParsedResult
├── prompts.py           # промпты и response_schema для Gemini
├── config.py            # загрузка .env
└── requirements.txt
```

Обрати внимание: `whisper.py`, `parser.py`, `vision.py` объединены в один файл `gemini.py` — три функции в одном сервисе.

---

## Режимы работы бота

### Режим 1 — Голосовое сообщение

**Триггер:** пользователь отправляет voice message

**Флоу:**
1. Бот отвечает: `⏳ Слушаю...`
2. Скачивает `.ogg` файл через Telegram API
3. Отправляет `.ogg` напрямую в Gemini (конвертация не нужна)
4. Gemini транскрибирует + парсит за один вызов → возвращает структуру через `response_schema`
5. Показывает результат с кнопками подтверждения

**Пример голосового:**
> "В Магнуме бананы девятьсот двадцать, авокадо тысяча четыреста девяносто, помидоры семьсот восемьдесят"

**Ожидаемый результат:**
```json
{
  "source": "magnum",
  "items": [
    {"product": "банан", "price": 920, "unit": "кг"},
    {"product": "авокадо", "price": 1490, "unit": "шт"},
    {"product": "помидор", "price": 780, "unit": "кг"}
  ]
}
```

**Важно:** Gemini делает транскрипцию и парсинг за один запрос — не нужен отдельный шаг "сначала в текст, потом парсим текст".

---

### Режим 2 — Фото/скриншот

**Триггер:** пользователь отправляет фото

**Флоу:**
1. Бот отвечает: `🔍 Распознаю цены...`
2. Скачивает фото через Telegram API
3. Отправляет байты изображения в Gemini 2.0 Flash (vision)
4. Получает структуру через `response_schema`
5. Показывает результат с кнопками подтверждения

**Ожидаемое поведение:**
- Если на фото несколько товаров — парсит все
- Если источник не понятен по фото — спрашивает: `Откуда это фото?` (inline кнопки: Магнум / Тредс / Galmart / Arbuz / Яндекс Лавка)

---

### Режим 3 — Текстовые команды

| Команда | Действие |
|---|---|
| `/price банан 920 магнум` | Быстрый ввод — записывает **без подтверждения**, сразу в базу |
| `/price банан 920` | Ввод без источника → бот спрашивает источник inline-кнопками, потом сразу пишет |
| `/report` | Утренняя сводка: наши цены vs конкуренты по всем позициям |
| `/alerts` | Показать непросмотренные алерты |
| `/help` | Список команд |

**Парсинг `/price`:**
- Формат: `/price <товар> <цена> [источник]`
- Товар матчится по `products.name_aliases` (нечёткий поиск, lowercase)
- Источник: magnum/тредс/galmart/arbuz/лавка/алтын-орда (нечёткий матч)

---

## Подтверждение (критически важно)

**Правило:**
- `/price` — **без подтверждения**. Стоишь у полки, вводишь быстро, нет времени тапать кнопки. Бот отвечает: `✅ Записал: Банан — 920 ₸/кг (Магнум)`
- Голос и фото — **с подтверждением всегда**. Gemini может ошибиться в цифрах — цена 920 превращается в 9200, это катастрофа для дашборда.

**Формат сообщения подтверждения:**
```
✅ Распознал (Магнум):

  Банан — 920 ₸/кг
  Авокадо — 1 490 ₸/шт
  Помидор — 780 ₸/кг

Записать в базу?
```

**Inline кнопки:**
- `✅ Да, записать` → callback `confirm_yes:{session_id}`
- `✏️ Исправить` → callback `confirm_edit:{session_id}` → бот просит прислать исправление текстом
- `❌ Отмена` → callback `confirm_cancel:{session_id}`

**Сессии:** хранятся в памяти (`dict`) с TTL 5 минут. Ключ — `session_id` (uuid4). Значение — список `PriceEntry`.

---

## Алерты

После каждой успешной записи в Supabase — автоматически проверять:

1. **gap_shrink** — если разница между ценой конкурента и нашей ценой сократилась до < 15%:
   > ⚠️ Банан: разрыв с Магнумом сократился до 10% (было 20%)

2. **price_drop** — если конкурент снизил цену более чем на 10% от предыдущего снимка:
   > 🔴 Авокадо: Магнум снизил с 1 630 до 1 490 ₸ (−8.6%)

3. **price_spike** — если конкурент поднял цену более чем на 10%:
   > 🟢 Гранат: Тредс поднял с 2 500 до 2 800 ₸ (+12%). Можно поднять нашу цену.

Алерты отправляются в тот же чат сразу после подтверждения записи.

---

## Gemini: реализация (services/gemini.py)

### Инициализация
```python
import google.generativeai as genai
from config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")
```

### response_schema (prompts.py)
```python
PRICE_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "nullable": True},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "price":   {"type": "number"},
                    "unit":    {"type": "string"}
                },
                "required": ["product", "price", "unit"]
            }
        }
    },
    "required": ["items"]
}
```

Передаётся в `generation_config={"response_mime_type": "application/json", "response_schema": PRICE_SCHEMA}` — Gemini гарантирует валидный JSON по схеме. `json.loads()` не нужен, `try/except` только для сетевых ошибок.

### Голос
```python
async def transcribe_and_parse(ogg_bytes: bytes) -> dict:
    audio_part = {"mime_type": "audio/ogg", "data": ogg_bytes}
    response = model.generate_content(
        [VOICE_PROMPT, audio_part],
        generation_config={"response_mime_type": "application/json", "response_schema": PRICE_SCHEMA}
    )
    return response.parsed  # уже dict, не строка
```

### Фото
```python
async def parse_photo(image_bytes: bytes) -> dict:
    image_part = {"mime_type": "image/jpeg", "data": image_bytes}
    response = model.generate_content(
        [VISION_PROMPT, image_part],
        generation_config={"response_mime_type": "application/json", "response_schema": PRICE_SCHEMA}
    )
    return response.parsed
```

---

## Промпты (prompts.py)

### VOICE_PROMPT
```
Ты парсер цен для продуктового стартапа в Алматы.
Прослушай голосовое сообщение и извлеки список товаров с ценами.

Правила:
- source: один из [magnum, treds, galmart, arbuz, lavka, altyn_orda]. Если не упомянут — null.
- product: название товара в именительном падеже, строчными буквами (банан, авокадо, помидор...)
- price: число тенге (только цифры). Числа прописью конвертируй в цифры: "девятьсот двадцать" = 920
- unit: "кг" или "шт". Если не упомянуто — угадай по товару (авокадо/ананас/гранат = шт, остальное = кг)
```

### VISION_PROMPT
```
Ты парсер цен с фотографий ценников и скриншотов приложений доставки.
На изображении могут быть ценники казахстанских супермаркетов или скриншот мобильного приложения.

Извлеки все товары категории "фрукты и овощи" с ценами.

Правила:
- product: название товара строчными буквами (банан, авокадо, помидор...)
- price: цена за единицу в тенге (число)
- unit: "кг" или "шт"
- source: если виден логотип магазина или название приложения — укажи (magnum/treds/galmart/arbuz/lavka), иначе null
- Игнорируй товары не из фруктов/овощей
```

---

## Сообщение `/report`

```
📊 Сводка цен — пт 30 мая

Позиция       PASH    Магнум   Разница
──────────────────────────────────────
Банан/кг       787 ₸    920 ₸   −14% ✅
Авокадо/шт   1100 ₸   1490 ₸   −26% ✅
Гранат/кг    1250 ₸   3053 ₸   −59% 🔥
Помидор/кг    625 ₸    780 ₸   −20% ✅
Огурцы/кг     500 ₸    680 ₸   −26% ✅

⚠️ Нет данных (>3 дней): Ананас, Грейпфрут
```

Данные берутся из `price_snapshots` — последний снимок по каждому источнику за последние 7 дней.

---

## Безопасность

- Бот отвечает **только** пользователям из `ALLOWED_USER_IDS`
- Все остальные получают: `❌ Доступ закрыт`
- Проверка на каждый входящий update (middleware)

---

## Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Gemini не распознал голос | `🤷 Не смог разобрать. Попробуй ещё раз или введи текстом: /price банан 920 магнум` |
| Gemini вернул пустой список | `🤷 Не нашёл цен. Попробуй ещё раз или введи текстом.` |
| Supabase недоступен | `⚠️ База недоступна. Данные не записаны. Попробуй позже.` |
| Товар не найден в products | `Не знаю такой товар: "хурма". Добавить в справочник? [Да / Нет]` |
| Сессия истекла (>5 мин) | `⏰ Сессия истекла. Отправь данные заново.` |
| Ошибка Gemini API | Retry 1 раз с задержкой 2с, потом сообщение об ошибке |

---

## Зависимости (requirements.txt)

```
python-telegram-bot==21.5
google-generativeai==0.7.2
supabase==2.5.0
python-dotenv==1.0.0
aiohttp==3.9.5
```

`pydub` и `ffmpeg` больше не нужны — Gemini принимает `.ogg` нативно.

---

## Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

Обрати внимание: `ffmpeg` убран из Dockerfile.

---

## Порядок разработки (для Claude Code)

1. `config.py` — загрузка .env, ALLOWED_USER_IDS
2. `models.py` — dataclasses PriceEntry, ParsedResult, Session
3. `prompts.py` — VOICE_PROMPT, VISION_PROMPT, PRICE_SCHEMA
4. `services/gemini.py` — единый клиент: transcribe_and_parse(), parse_photo(), parse_text()
5. `services/supabase.py` — insert_snapshot(), get_latest_prices(), insert_alert()
6. `services/alerts.py` — check_alerts() после каждой записи
7. `handlers/confirm.py` — inline-кнопки, сессии в памяти
8. `handlers/voice.py` — voice handler
9. `handlers/photo.py` — photo handler
10. `handlers/text.py` — /price, /report, /alerts, /help
11. `main.py` — Application, регистрация handlers, polling

---

## Тестирование вручную

После запуска проверить:
- [ ] Отправить голосовое: `"В Магнуме бананы девятьсот, авокадо тысяча пятьсот"` → должен распознать 2 позиции
- [ ] Нажать `✅ Да` → должно записаться в Supabase
- [ ] Отправить скриншот из приложения Магнума → должен распознать позиции
- [ ] `/price банан 920 магнум` → должно записаться **сразу** без подтверждения, ответ `✅ Записал`
- [ ] `/report` → должна выйти сводка
- [ ] Отправить сообщение с неразрешённого аккаунта → `❌ Доступ закрыт`

---

*PASH · pash.kz · Алматы · 2026*
