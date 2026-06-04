from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.gemini import parse_photo
from services.supabase import get_or_create_product
from handlers.confirm import create_confirmation_message
from sources import SOURCE_MAP
import logging

logger = logging.getLogger(__name__)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos."""
    await update.message.reply_text("🔍 Анализирую...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        parsed = await parse_photo(bytes(photo_bytes))

        # Алтын-Орда: фото ящика обычно без цены — спросить цену и вес
        effective_source = parsed.source or (parsed.items[0].source if parsed.items else None)
        if effective_source == "altyn_orda" and parsed.items:
            item = parsed.items[0]
            product, created = await get_or_create_product(item.product, default_markup=25)
            if created:
                await update.message.reply_text(f'➕ Добавил новый товар: {item.product} (наценка 25%)')
            if product and (not item.price or item.price <= 0):
                # Нет цены в фото — спросить "цена вес"
                context.user_data["pending_weight"] = {
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "container_price": None,   # заполним когда получим от пользователя
                    "container": "ящик",        # по умолчанию
                    "unit": item.unit or "кг",
                    "markup_pct": product.get("markup_pct"),
                    "our_price": product.get("our_price"),
                    "awaiting_price_and_weight": True,  # флаг особого режима
                }
                await update.message.reply_text(
                    f"📦 {product['name'].capitalize()} (Алтын-Орда)\n"
                    f"Напиши цену и вес через пробел:\n"
                    f"<i>Например: 19000 19</i>",
                    parse_mode="HTML"
                )
                return

        # Если ничего не распознано ИЛИ source неизвестен → показать кнопки источника
        if not parsed.items or not effective_source:
            # Сохраняем частично распознанный товар (если есть) для использования после выбора источника
            product_hint = parsed.items[0].product if parsed.items else None
            context.user_data["pending_photo"] = parsed
            context.user_data["photo_product_hint"] = product_hint
            buttons = [
                [
                    InlineKeyboardButton(f"{SOURCE_MAP[k]['emoji']} {SOURCE_MAP[k]['display']}", callback_data=f"source_photo:{k}")
                    for k in SOURCE_MAP.keys()
                ]
            ]
            hint = f" (распознал: {product_hint})" if product_hint else ""
            await update.message.reply_text(f"Откуда это фото?{hint}", reply_markup=InlineKeyboardMarkup(buttons))
            return

        # Source известен и цена есть → прямо confirmation
        message, markup = await create_confirmation_message(parsed)
        await update.message.reply_text(message, reply_markup=markup)

    except Exception as e:
        logger.error(f"Photo handler error: {str(e)}", exc_info=True)
        await update.message.reply_text("Фото не читается. Попробуй ещё раз.")
