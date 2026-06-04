# PASH Price Bot 🔬

Внутренний бот мониторинга цен для команды PASH (Алматы).  
Принимает голос, фото, текст → парсит через Gemini → записывает в Supabase.

## Стек

- Python 3.11
- python-telegram-bot 21.5
- Google Gemini 2.5 Flash
- Supabase (PostgreSQL)

## Деплой на Railway

### 1. Создай сервис на Railway

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. Выбери репозиторий `pash-price-bot`

### 2. Добавь переменные окружения

В Railway → Variables добавь:

```
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
ALLOWED_USER_IDS=99755510
WEBHOOK_URL=https://ИМЯ.railway.app/webhook
```

> `PORT` Railway подставляет автоматически — не добавляй вручную.

### 3. Задеплой

Railway автоматически запустит `python main.py` (из Procfile).  
Бот сам зарегистрирует webhook при старте.

## Локальная разработка

```bash
cp .env.example .env
# Заполни .env (WEBHOOK_URL оставь пустым → будет polling)
pip install -r requirements.txt
python main.py
```

## Переменные окружения

| Переменная | Обязательная | Описание |
|------------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен от BotFather |
| `GEMINI_API_KEY` | ✅ | Google AI Studio |
| `SUPABASE_URL` | ✅ | URL проекта Supabase |
| `SUPABASE_ANON_KEY` | ✅ | Anon key Supabase |
| `ALLOWED_USER_IDS` | ✅ | Telegram user ID через запятую |
| `WEBHOOK_URL` | ⚪ | Пусто → polling, задан → webhook |
| `PORT` | ⚪ | Railway подставляет сам |

## Команды бота

| Команда | Описание |
|---------|----------|
| `/price товар цена [источник]` | Быстрая запись цены |
| `/report` | Сводка цен по всем источникам |
| `/alerts` | Непросмотренные алерты |
| `/help` | Справка |

Или просто пиши текстом: `банан 920 магнум`
