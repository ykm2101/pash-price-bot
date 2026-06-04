# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Set up environment:**
Copy `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from BotFather on Telegram
- `GEMINI_API_KEY` — from https://aistudio.google.com/apikey
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` — from Supabase dashboard
- `ALLOWED_USER_IDS` — comma-separated Telegram user IDs

**Run the bot:**
```bash
python main.py
```

**Development notes:**
- Bot uses `python-telegram-bot` v21 with async/await
- All Gemini API calls (voice, vision, text) use a single `google-generativeai` SDK client
- No external audio conversion needed — Gemini accepts `.ogg` files natively
- Tests are manual (see "Testing" section in PASH_PriceBot_TZ.md)

---

## Architecture Overview

### Core Flow: Three Input Modes

1. **Voice messages** → Gemini transcribes + parses price data → confirmation prompt → database write
2. **Photo/screenshot** → Gemini vision extracts prices → confirmation prompt → database write  
3. **Text command** (`/price`) → immediate database write (no confirmation needed for CLI-style input)

All three flows converge on the same `PriceEntry` model and database layer. Confirmation is critical for voice/photo (Gemini can misread numbers) but skipped for `/price` commands (typed by user, trusted).

### Four Service Layers

| Layer | Purpose | Files |
|-------|---------|-------|
| **Config** | Load and validate environment | `config.py` |
| **Models** | Data structures (dataclasses) | `models.py` |
| **Services** | Core business logic (Gemini, Supabase, alerts) | `services/` |
| **Handlers** | Telegram event handlers | `handlers/` |

### Key Design Patterns

**Gemini as a unified AI layer:**
- Single client instance (`genai.GenerativeModel("gemini-2.0-flash")`)
- Three functions in `services/gemini.py`: `transcribe_and_parse()`, `parse_photo()`, `parse_text()`
- All use `response_schema` for guaranteed JSON compliance — no manual parsing needed
- Prompts live in `prompts.py` for easy tweaking

**Session management for confirmation:**
- Voice/photo results stored in memory with session IDs (UUID)
- 5-minute TTL for sessions
- Inline callbacks (`confirm_yes`, `confirm_edit`, `confirm_cancel`) reference session IDs
- After confirmation, atomic write to Supabase + alert generation

**Alert system (post-write):**
- `services/alerts.py` checks three rules after every price snapshot: `gap_shrink` (margin tightening), `price_drop` (competitor cuts price >10%), `price_spike` (competitor raises >10%)
- Alerts stored in database and sent to user immediately

---

## Database Schema

Three core tables in Supabase:

1. **`products`** — Reference table (name, aliases, unit, category, our_price)
2. **`price_snapshots`** — Time-series of competitor prices (product_id, source, price, recorded_at)
3. **`alerts`** — Generated alerts (product_id, type, message, seen, created_at)

Initial setup requires running the SQL from PASH_PriceBot_TZ.md to create tables.

---

## Development Order

Follow this sequence when building:

1. `config.py` — Environment variable loading
2. `models.py` — `PriceEntry`, `ParsedResult` dataclasses
3. `prompts.py` — Gemini prompts and `PRICE_SCHEMA`
4. `services/gemini.py` — Unified Gemini client (transcribe + vision + text)
5. `services/supabase.py` — Database CRUD operations
6. `services/alerts.py` — Alert checking logic
7. `handlers/confirm.py` — Inline button callbacks and session management
8. `handlers/voice.py`, `handlers/photo.py`, `handlers/text.py` — Input handlers
9. `main.py` — Application setup, handler registration, polling loop

---

## Critical Implementation Details

**Response schema guarantee:**
- When using `response_schema` with Gemini, the returned `response.parsed` is already a Python dict — no JSON decoding needed, only network error handling

**Async handler pattern:**
- All handlers are async (`async def handler(...)`)
- Use `await client.download(...)` for Telegram file downloads
- Session lookups and database ops should be awaited

**Source matching:**
- Sources are fuzzy-matched: "magnum", "тредс", "galmart", "arbuz", "лавка", "altyn_orda"
- Product names matched against `products.name_aliases` (lowercase, fuzzy)
- Gemini prompts handle Cyrillic input naturally

**Error handling priorities:**
- Network errors (Gemini, Supabase) → retry once, then user-facing error message
- Parsing errors (empty results) → ask user to retry or use text input
- Unknown product → suggest adding to reference table
- Expired session → ask user to resend

---

## Deployment

- Target: Railway or Fly.io (single Docker container)
- Dockerfile provided in TZ — uses `python:3.11-slim`
- No `ffmpeg` dependency needed (Gemini handles `.ogg` natively)
- Environment variables injected at deploy time

---

## Testing Checklist

Manual testing required (see PASH_PriceBot_TZ.md for detailed steps):
- Voice message parsing (Cyrillic numbers)
- Photo recognition from store apps
- `/price` command with/without source
- `/report` summary generation
- Inline confirmation buttons
- Alert triggers
- Access control (ALLOWED_USER_IDS)
