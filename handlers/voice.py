from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.gemini import transcribe_and_parse
from services.supabase import get_or_create_product, get_container_weight
from services.wholesale import resolve_price_per_kg, format_conversion_note, normalize_container
from handlers.confirm import create_confirmation_message, sessions
from models import Session, PriceEntry
from sources import SOURCE_MAP, SOURCE_LIST
import logging

logger = logging.getLogger(__name__)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice messages."""
    user_id = update.effective_user.id

    await update.message.reply_text("⏳ Слушаю...")

    try:
        logger.info(f"Voice received from user {user_id}")
        voice_file = await update.message.voice.get_file()
        logger.info(f"Voice file downloaded: {len(voice_file.file_path)} bytes")

        ogg_bytes = await voice_file.download_as_bytearray()
        logger.info(f"OGG bytes received: {len(ogg_bytes)} bytes")

        parsed = await transcribe_and_parse(bytes(ogg_bytes))
        logger.info(f"Parsed result: source={parsed.source}, items={len(parsed.items)}")

        if not parsed.items:
            await update.message.reply_text("🤷 Не нашёл цен. Попробуй ещё раз или введи текстом.")
            return

        # Determine language for menu
        language = getattr(parsed, 'language', 'ru')  # ru, kk, or mixed
        logger.info(f"Voice handler: language={language} (from parsed)")

        # Normalize source on all items from top-level if missing
        effective_source = parsed.source
        for it in parsed.items:
            if not it.source and effective_source:
                it.source = effective_source

        item = parsed.items[0]

        # Если нет source → показать кнопки
        if not item.source:
            session = Session(items=parsed.items, language=language)
            sessions[session.session_id] = session
            context.user_data["pending_voice_session"] = session.session_id
            buttons = [
                [
                    InlineKeyboardButton(f"{SOURCE_MAP[k]['emoji']} {SOURCE_MAP[k]['display']}", callback_data=f"source_voice:{session.session_id}:{k}")
                    for k in SOURCE_LIST
                ]
            ]
            await update.message.reply_text("Откуда это цена?", reply_markup=InlineKeyboardMarkup(buttons))
            return

        # === АЛТЫН-ОРДА с контейнером: пересчитать в цену за кг ===
        if not item.container and item.container_weight_kg:
            item.container = "ящик"
        if item.source == "altyn_orda" and item.container:
            container = normalize_container(item.container)
            product, created = await get_or_create_product(item.product, default_markup=25)
            if created:
                await update.message.reply_text(f'➕ Добавил новый товар: {item.product} (наценка 25%)')

            if product:
                price_per_kg, weight_used, needs_weight = await resolve_price_per_kg(product["id"], item)

                if needs_weight:
                    # Неизвестный вес → спросить
                    context.user_data["pending_weight"] = {
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "container_price": item.price,
                        "container": container,
                        "unit": item.unit,
                        "markup_pct": product.get("markup_pct"),
                        "our_price": product.get("our_price"),
                    }
                    await update.message.reply_text(
                        f"📦 {product['name'].capitalize()}, {container} — {item.price:,.0f}₸\n"
                        f"Сколько кг в {container}е? (напиши число, например: 18)"
                    )
                    return

                # Пересчитано → обновить item и показать confirmation
                conversion_note = format_conversion_note(item.price, container, weight_used, price_per_kg)
                item.price = price_per_kg
                item.unit = "кг"
                item.container = None
                item.container_weight_kg = None
                parsed.items[0] = item

                # Показать confirmation с пометкой о пересчёте
                message, markup = await create_confirmation_message(parsed, language=language)
                await update.message.reply_text(f"🔄 {conversion_note}", parse_mode=None)
                await update.message.reply_text(message, reply_markup=markup)
                return

        # Обычная цена → показать подтверждение
        logger.info(f"Calling create_confirmation_message with language={language}")
        message, markup = await create_confirmation_message(parsed, language=language)
        await update.message.reply_text(message, reply_markup=markup)

    except Exception as e:
        error_str = str(e)
        logger.error(f"Voice handler error: {error_str}", exc_info=True)

        if "429" in error_str or "quota" in error_str.lower():
            await update.message.reply_text("⚠️ Лимит Gemini API исчерпан. Используй /price команду вместо голоса.")
        elif "Voice parsing failed" in error_str:
            await update.message.reply_text("🤷 Не смог разобрать. Попробуй ещё раз или введи текстом: /price банан 920 магнум")
        else:
            await update.message.reply_text(f"❌ Ошибка: {error_str[:100]}")
