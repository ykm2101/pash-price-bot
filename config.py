import os
from dotenv import load_dotenv

load_dotenv()

def _require(name):
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"MISSING ENV VAR: {name}  — add it in Railway → Variables")
    return val

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY     = _require("GEMINI_API_KEY")
SUPABASE_URL       = _require("SUPABASE_URL")
SUPABASE_ANON_KEY  = _require("SUPABASE_ANON_KEY")
ALLOWED_USER_IDS = set(
    int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()
)

# Webhook (Railway) — если не задан, работаем в polling режиме локально
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", 8000))
