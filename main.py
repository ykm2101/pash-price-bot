import logging
import os
import sys
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, WEBHOOK_URL, PORT
from handlers.voice import handle_voice
from handlers.photo import handle_photo
from handlers.text import handle_price_command, handle_report_command, handle_alerts_command, handle_help_command, handle_free_text
from handlers.confirm import handle_confirm_callback, cleanup_expired_sessions

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def access_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized."""
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.effective_message.reply_text("❌ Доступ закрыт")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await access_check(update, context):
        return
    await update.message.reply_text("Q на связи. Голос, фото или текст — принимаю в любом виде.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    async def price_cmd_safe(update, context):
        if await access_check(update, context): await handle_price_command(update, context)
    async def report_cmd_safe(update, context):
        if await access_check(update, context): await handle_report_command(update, context)
    async def alerts_cmd_safe(update, context):
        if await access_check(update, context): await handle_alerts_command(update, context)
    async def help_cmd_safe(update, context):
        if await access_check(update, context): await handle_help_command(update, context)
    async def voice_safe(update, context):
        if await access_check(update, context): await handle_voice(update, context)
    async def photo_safe(update, context):
        if await access_check(update, context): await handle_photo(update, context)
    async def text_safe(update, context):
        if await access_check(update, context): await handle_free_text(update, context)
    async def callback_safe(update, context):
        if await access_check(update, context): await handle_confirm_callback(update, context)

    app.add_handler(CommandHandler("price", price_cmd_safe))
    app.add_handler(CommandHandler("report", report_cmd_safe))
    app.add_handler(CommandHandler("alerts", alerts_cmd_safe))
    app.add_handler(CommandHandler("help", help_cmd_safe))
    app.add_handler(MessageHandler(filters.VOICE, voice_safe))
    app.add_handler(MessageHandler(filters.PHOTO, photo_safe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_safe))
    app.add_handler(CallbackQueryHandler(callback_safe))

    async def error_handler(update, context):
        logger.error(f"Update {update} caused error {context.error}")
    app.add_error_handler(error_handler)

    if WEBHOOK_URL:
        # Production: webhook mode (Railway)
        logger.info(f"Starting webhook on port {PORT}, url={WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path="webhook",
        )
    else:
        # Local dev: polling mode
        logger.info("Starting polling (local dev)...")
        app.run_polling()

if __name__ == "__main__":
    main()
