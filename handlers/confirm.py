from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from models import Session
from services.supabase import insert_snapshot, get_product_by_name, get_or_create_product, update_our_price, get_product_with_markup, get_latest_price_by_source
from sources import get_source_display_name
from services.alerts import check_alerts
import logging

logger = logging.getLogger(__name__)
sessions = {}

async def create_confirmation_message(parsed_result, language: str = "ru") -> tuple[str, InlineKeyboardMarkup]:
    """Create confirmation message with inline buttons in selected language."""
    logger.info(f"create_confirmation_message: language={language}, parsed_result.language={getattr(parsed_result, 'language', 'N/A')}")

    # Propagate top-level source to items that don't have one
    if parsed_result.source:
        for item in parsed_result.items:
            if not item.source:
                item.source = parsed_result.source

    session = Session(items=parsed_result.items, language=language)
    sessions[session.session_id] = session

    source = parsed_result.source or ("Белгісіз" if language == "kk" else "Неизвестно")
    items_text = "\n".join([
        f"  {item.product.capitalize()} — {item.price:,.0f} ₸/{item.unit}"
        for item in parsed_result.items
    ])

    logger.info(f"Using language for menu: {language}")

    # Language-specific buttons and messages
    # If language is 'kk' or 'mixed' (contains Kazakh), show Kazakh menu
    if language in ["kk", "mixed"]:
        logger.info(f"Showing KAZAKH menu for language={language}")
        message = f"📋 {source}:\n\n{items_text}\n\nБазаға жазамын?"
        buttons = [
            [
                InlineKeyboardButton("✅ Жаз", callback_data=f"confirm_yes:{session.session_id}"),
                InlineKeyboardButton("✏️ Түзету", callback_data=f"confirm_edit:{session.session_id}")
            ],
            [InlineKeyboardButton("✖ Болдырмау", callback_data=f"confirm_cancel:{session.session_id}")]
        ]
    else:
        message = f"📋 {source}:\n\n{items_text}\n\nЗафиксировать?"
        buttons = [
            [
                InlineKeyboardButton("✅ В базу", callback_data=f"confirm_yes:{session.session_id}"),
                InlineKeyboardButton("✏️ Исправить", callback_data=f"confirm_edit:{session.session_id}")
            ],
            [InlineKeyboardButton("✖ Отставить", callback_data=f"confirm_cancel:{session.session_id}")]
        ]

    return message, InlineKeyboardMarkup(buttons)

async def handle_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Handle confirmation button clicks."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 1)
    action = parts[0]
    session_id = parts[1] if len(parts) > 1 else None

    logger.info(f"Callback: action={action}, session_id={session_id}, total_sessions={len(sessions)}, session_exists={session_id in sessions if session_id else False}")

    # ── PARTIAL DIALOG CALLBACKS ──────────────────────────────────────
    if action in ("partial_source", "partial_container", "partial_unit",
                  "partial_confirm", "partial_cancel", "partial_edit"):
        from handlers.dialog import ask_next, format_known, confirm_buttons

        raw_parts = query.data.split(":")
        # formats: partial_source:sid:value  or  partial_cancel:sid
        if len(raw_parts) >= 2:
            p_session_id = raw_parts[1]
            p_value = raw_parts[2] if len(raw_parts) > 2 else None
        else:
            return None

        if action == "partial_cancel":
            if p_session_id in sessions:
                del sessions[p_session_id]
            context.user_data.pop("partial_session_id", None)
            await query.edit_message_text("Отменено ✌️")
            return None

        if p_session_id not in sessions:
            await query.edit_message_text("⏰ Данные устарели.")
            return None

        session = sessions[p_session_id]
        p = session.partial

        if action == "partial_source":
            p['source'] = p_value
        elif action == "partial_container":
            p['container'] = p_value
        elif action == "partial_unit":
            p['unit'] = p_value
        elif action == "partial_edit":
            # Сбросить последнее поле и переспросить
            for field in ['source', 'container', 'price', 'product']:
                if p.get(field):
                    p[field] = None
                    break
            async def reply_edit(msg, **kwargs):
                await query.message.reply_text(msg, **kwargs)
            await ask_next(session, reply_edit)
            return None

        elif action == "partial_confirm":
            # Всё заполнено — записать в БД
            product_name = p.get('product')
            price = p.get('price')
            source = p.get('source')
            unit = p.get('unit', 'кг')
            container = p.get('container') or ("ящик" if source == "altyn_orda" else None)
            weight = p.get('container_weight_kg')

            try:
                is_wholesale = (source == 'altyn_orda')
                product, created = await get_or_create_product(product_name, default_markup=25 if is_wholesale else None)
                if created:
                    await query.message.reply_text(f'➕ Добавил новый товар: {product_name}')

                if is_wholesale and container and price:
                    from services.wholesale import format_conversion_note, normalize_container
                    from services.supabase import insert_wholesale_lot, get_container_weight as gcw

                    # Resolve weight: use stored if available
                    if not weight:
                        weight = await gcw(product['id'], container)

                    if not weight:
                        # Ask user for weight via pending_weight flow
                        context.user_data["pending_weight"] = {
                            "product_id": product['id'],
                            "product_name": product['name'],
                            "container_price": price,
                            "container": container,
                            "unit": unit,
                            "markup_pct": (await get_product_with_markup(product['id']) or {}).get("markup_pct"),
                            "our_price": (await get_product_with_markup(product['id']) or {}).get("our_price"),
                        }
                        del sessions[p_session_id]
                        context.user_data.pop("partial_session_id", None)
                        await query.edit_message_text(
                            f"📦 {product['name'].capitalize()}, {container} — {price:,.0f}₸\n"
                            f"Сколько кг в {container}е? (напр. 18)"
                        )
                        return None

                    price_per_kg = round(price / weight, 1)
                    raw = f"{price}₸/{container} ({weight}кг) → {price_per_kg}₸/кг"
                    prev = await get_latest_price_by_source(product['id'], 'altyn_orda')
                    old_price = prev['price'] if prev else None
                    await insert_snapshot(product['id'], 'altyn_orda', price_per_kg, unit, raw)
                    product_data = await get_product_with_markup(product['id'])
                    markup_pct = (product_data or {}).get('markup_pct') or 25
                    our = round(price_per_kg * (1 + markup_pct / 100))
                    await insert_wholesale_lot(product['id'], container, price, weight, price_per_kg, our, raw)
                    note = format_conversion_note(price, container, weight, price_per_kg)
                    await query.edit_message_text(f"✅ Записал: {product_name.capitalize()}\n{note}")

                    msg = f"💡 {price_per_kg:,.1f}₸/кг × +{markup_pct}% = {our:,.0f}₸/кг\n\nУстановить как нашу цену?"
                    buttons = [
                        [
                            InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product['id']}:{our}"),
                            InlineKeyboardButton("✏️ Своя цена", callback_data=f"set_custom_price:{product['id']}")
                        ],
                        [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_price:{product['id']}")]
                    ]
                    await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

                else:
                    prev = await get_latest_price_by_source(product['id'], source)
                    old_price = prev['price'] if prev else None
                    await insert_snapshot(product['id'], source, price, unit, f"{product_name} {price} {source}")
                    source_name = get_source_display_name(source)
                    await query.edit_message_text(f"✅ Записал: {product_name.capitalize()} — {price:,.0f} ₸/{unit} ({source_name})")

                    product_full = await get_product_with_markup(product['id'])
                    our_price = (product_full or {}).get('our_price')
                    if our_price:
                        from services.alerts import check_alerts
                        alerts = await check_alerts(product['id'], source, price, our_price, old_price=old_price)
                        for alert in alerts:
                            await query.message.reply_text(alert)

                del sessions[p_session_id]
                context.user_data.pop("partial_session_id", None)

            except Exception as e:
                logger.error(f"partial_confirm error: {e}", exc_info=True)
                await query.edit_message_text(f"❌ Ошибка: {str(e)[:80]}")
            return None

        # После изменения поля — задать следующий вопрос или подтверждение
        async def reply_partial(msg, **kwargs):
            await query.message.reply_text(msg, **kwargs)
        await ask_next(session, reply_partial)
        return None

    # Handle voice source selection: source_voice:session_id:source_id
    if action == "source_voice":
        parts = query.data.split(":")
        if len(parts) == 3:
            _, session_id, source_id = parts
            if session_id in sessions:
                session = sessions[session_id]
                for item in session.items:
                    item.source = source_id

                # Алтын-Орда: resolve container price → price per kg before showing confirmation
                if source_id == "altyn_orda" and session.items:
                    item = session.items[0]
                    item.container = item.container or "ящик"
                    from services.supabase import get_or_create_product as _gocp
                    from services.wholesale import resolve_price_per_kg, format_conversion_note, normalize_container
                    product, _ = await _gocp(item.product, default_markup=25)
                    container = normalize_container(item.container)
                    price_per_kg, weight_used, needs_weight = await resolve_price_per_kg(product["id"], item)
                    if needs_weight:
                        context.user_data["pending_weight"] = {
                            "product_id": product["id"],
                            "product_name": product["name"],
                            "container_price": item.price,
                            "container": container,
                            "unit": item.unit,
                            "markup_pct": product.get("markup_pct"),
                            "our_price": product.get("our_price"),
                        }
                        del sessions[session_id]
                        await query.message.reply_text(
                            f"📦 {product['name'].capitalize()}, {container} — {item.price:,.0f}₸\n"
                            f"Сколько кг в {container}е? (напр. 18)"
                        )
                        return None
                    note = format_conversion_note(item.price, container, weight_used, price_per_kg)
                    item.price = price_per_kg
                    item.container = None
                    item.container_weight_kg = None
                    session.items[0] = item
                    await query.message.reply_text(f"🔄 {note}")

                from models import ParsedResult
                parsed = ParsedResult(source=source_id, items=session.items, language=session.language)
                message, markup = await create_confirmation_message(parsed, language=session.language)
                await query.message.reply_text(message, reply_markup=markup)
                return None

    # Handle photo source selection: source_photo:source_id
    if action == "source_photo":
        source_id = session_id  # source_photo:magazin → session_id = "magazin"
        product_hint = context.user_data.pop("photo_product_hint", None)
        parsed = context.user_data.pop("pending_photo", None)

        if source_id == "altyn_orda":
            # Для оптовки — спросить товар+цена+вес одной строкой
            hint = f" ({product_hint})" if product_hint else ""
            context.user_data["pending_weight"] = {
                "product_id": None,  # заполним после ввода
                "product_name": product_hint,
                "container_price": None,
                "container": "ящик",
                "unit": "кг",
                "markup_pct": None,
                "our_price": None,
                "awaiting_price_and_weight": True,
                "awaiting_product_too": not bool(product_hint),  # нужно ли спрашивать товар
            }
            if product_hint:
                await query.message.reply_text(
                    f"📦 {product_hint.capitalize()} (Алтын-Орда)\n"
                    f"Напиши цену и вес: <i>19000 19</i>",
                    parse_mode="HTML"
                )
            else:
                await query.message.reply_text(
                    f"📦 Алтын-Орда\n"
                    f"Напиши товар, цену и вес: <i>банан 19000 19</i>",
                    parse_mode="HTML"
                )
        elif parsed and parsed.items:
            # Обычный источник с распознанными товарами
            parsed.source = source_id
            message, markup = await create_confirmation_message(parsed)
            await query.message.reply_text(message, reply_markup=markup)
        else:
            # Нет товаров — спросить цену текстом
            context.user_data["pending_manual_source"] = source_id
            await query.message.reply_text(
                f"Напиши товар и цену:\n<i>банан 990</i>",
                parse_mode="HTML"
            )
        return None

    # Handle text source selection: source_text:product_id:price:unit:source_id
    if action == "source_text":
        parts = query.data.split(":")
        if len(parts) == 5:
            _, product_id, price_str, unit, source_id = parts
            try:
                product_id = int(product_id)
                price = float(price_str)

                # Получаем предыдущую цену ДО вставки
                prev_snap = await get_latest_price_by_source(product_id, source_id)
                old_price_for_alert = prev_snap["price"] if prev_snap else None

                # Алтын-Орда → price это цена КОНТЕЙНЕРА, нужен вес
                if source_id == "altyn_orda":
                    product_data = await get_product_with_markup(product_id)
                    stored_weight = None
                    if product_data:
                        weights = (await get_latest_price_by_source(product_id, "altyn_orda") or {})
                        from services.supabase import get_container_weight
                        stored_weight = await get_container_weight(product_id, "ящик")

                    if stored_weight:
                        # Вес известен → сразу пересчитать
                        price_per_kg = round(price / stored_weight, 1)
                        markup_pct = (product_data or {}).get("markup_pct") or 25
                        suggested = round(price_per_kg * (1 + markup_pct / 100))
                        raw = f"{price}₸/ящик ({stored_weight}кг) → {price_per_kg}₸/кг"
                        await insert_snapshot(product_id, "altyn_orda", price_per_kg, unit, raw)
                        await query.edit_message_text(f"📌 {price:,.0f}₸ ÷ {stored_weight}кг = {price_per_kg}₸/кг")
                        msg = f"💡 Цена Пэш: {suggested}₸/кг (+{markup_pct}%)\n\nУстановить?"
                        buttons = [[
                            InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product_id}:{suggested}"),
                            InlineKeyboardButton("✖ Пропустить", callback_data=f"skip_price:{product_id}")
                        ]]
                        await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
                    else:
                        # Вес неизвестен → спросить
                        context.user_data["pending_weight"] = {
                            "product_id": product_id,
                            "product_name": f"product_{product_id}",
                            "container_price": price,
                            "container": "ящик",
                            "unit": unit,
                            "markup_pct": (product_data or {}).get("markup_pct") or 25,
                            "our_price": (product_data or {}).get("our_price"),
                        }
                        await query.edit_message_text(f"📦 {price:,.0f}₸ с Алтын-Орды. Вес ящика (кг)?")
                    return None
                # Магазин/Базар/Лавка → алерты
                else:
                    product_data = await get_product_with_markup(product_id)
                    if product_data:
                        our_price = product_data.get("our_price")
                        if our_price:
                            alerts = await check_alerts(product_id, source_id, price, our_price, old_price=old_price_for_alert)
                            for alert in alerts:
                                await query.message.reply_text(alert)
            except Exception as e:
                logger.error(f"source_text error: {str(e)}", exc_info=True)
                await query.edit_message_text(f"❌ Ошибка: {str(e)[:50]}")
            return None

    # These actions don't need a session — handle before session check
    if action == "set_our_price":
        parts = query.data.split(":")
        product_id = int(parts[1])
        suggested_price = int(parts[2])
        try:
            await update_our_price(product_id, suggested_price)
            await query.edit_message_text(f"✅ Цена Пэш обновлена: {suggested_price}₸")
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {str(e)[:50]}")
        return None

    if action == "set_custom_price":
        product_id = int(parts[1]) if len(parts) > 1 else None
        context.user_data["awaiting_custom_price"] = product_id
        await query.edit_message_text("Введи нашу цену (₸/кг):")
        return None

    if action == "skip_price":
        await query.edit_message_text("Пропущено.")
        return None

    if session_id not in sessions:
        await query.edit_message_text("⏰ Данные устарели. Повтори.")
        return None

    session = sessions[session_id]

    import time
    age_seconds = time.time() - session.created_at
    logger.info(f"Session {session_id}: age={age_seconds:.1f}s, language={session.language}, expired={session.is_expired()}")

    if session.is_expired():
        logger.info(f"Session expired: {session_id}")
        await query.edit_message_text("⏰ Данные устарели. Повтори.")
        del sessions[session_id]
        return None

    if action == "confirm_yes":
        try:
            # Write all items to database and collect confirmations
            confirmations = []
            for item in session.items:
                try:
                    is_wholesale = (item.source == "altyn_orda")
                    product, created = await get_or_create_product(item.product, default_markup=25 if is_wholesale else None)
                    if created:
                        info = "наценка 25%" if is_wholesale else "без наценки, цена конкурента"
                        await query.message.reply_text(f'➕ Добавил новый товар: {item.product} ({info})')

                    # If source is not set, cannot write to DB (must be one of: magazin, bazar, lavka, altyn_orda)
                    if not item.source:
                        await query.message.reply_text("❌ Не указан источник. Используй /help для справки.")
                        return None

                    source_to_write = item.source

                    # АЛТЫН-ОРДА: если item.container выставлен — это цена контейнера, нужна конвертация
                    if source_to_write == "altyn_orda" and item.container:
                        from services.wholesale import format_conversion_note, normalize_container
                        from services.supabase import insert_wholesale_lot, get_container_weight as gcw
                        container = normalize_container(item.container)
                        weight = item.container_weight_kg or await gcw(product["id"], container)
                        if not weight:
                            context.user_data["pending_weight"] = {
                                "product_id": product["id"],
                                "product_name": product["name"],
                                "container_price": item.price,
                                "container": container,
                                "unit": item.unit,
                                "markup_pct": (await get_product_with_markup(product["id"]) or {}).get("markup_pct"),
                                "our_price": product.get("our_price"),
                            }
                            await query.message.reply_text(
                                f"📦 {product['name'].capitalize()}, {container} — {item.price:,.0f}₸\n"
                                f"Сколько кг в {container}е? (напр. 18)"
                            )
                            continue
                        price_per_kg = round(item.price / weight, 1)
                        product_data = await get_product_with_markup(product["id"])
                        markup_pct = (product_data or {}).get("markup_pct") or 25
                        our = round(price_per_kg * (1 + markup_pct / 100))
                        raw = f"{item.price}₸/{container} ({weight}кг) → {price_per_kg}₸/кг"
                        prev_snap = await get_latest_price_by_source(product["id"], "altyn_orda")
                        old_price_for_alert = prev_snap["price"] if prev_snap else None
                        await insert_snapshot(product["id"], "altyn_orda", price_per_kg, item.unit, raw)
                        await insert_wholesale_lot(product["id"], container, item.price, weight, price_per_kg, our, raw)
                        note = format_conversion_note(item.price, container, weight, price_per_kg)
                        confirmations.append(f"📌 {product['name'].capitalize()}\n{note}")
                        msg = f"💡 {price_per_kg:,.1f}₸/кг × +{markup_pct}% = {our:,.0f}₸/кг\n\nУстановить как нашу цену?"
                        buttons = [
                            [
                                InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product['id']}:{our}"),
                                InlineKeyboardButton("✏️ Своя цена", callback_data=f"set_custom_price:{product['id']}")
                            ],
                            [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_price:{product['id']}")]
                        ]
                        await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
                        continue

                    # ОБЫЧНЫЙ ПУТЬ: вставка snapshot (цена уже per-kg)
                    prev_snap = await get_latest_price_by_source(product["id"], source_to_write)
                    old_price_for_alert = prev_snap["price"] if prev_snap else None

                    await insert_snapshot(
                        product["id"],
                        source_to_write,
                        item.price,
                        item.unit,
                        f"{item.product} {item.price} {source_to_write}",
                        source_detail=getattr(item, 'source_detail', None)
                    )

                    source_name = get_source_display_name(source_to_write)

                    if session.language in ["kk", "mixed"]:
                        confirmations.append(f"✅ Сақталды: {product['name'].capitalize()} — {item.price:,.0f} ₸/{item.unit} ({source_name})")
                    else:
                        confirmations.append(f"📌 {product['name'].capitalize()} — {item.price:,.0f} ₸/{item.unit} · {source_name}")

                    # Алтын-Орда без контейнера → цена уже per-kg, показать наценку
                    if source_to_write == "altyn_orda":
                        try:
                            product_data = await get_product_with_markup(product["id"])
                            if product_data and product_data.get("markup_pct"):
                                markup_pct = product_data["markup_pct"]
                                suggested_price = item.price * (1 + markup_pct / 100)
                                msg = f"💡 {product['name'].capitalize()}: {item.price:,.0f}₸/кг × +{markup_pct}% = {suggested_price:,.0f}₸/кг\n\nУстановить как нашу цену?"
                                buttons = [
                                    [
                                        InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product['id']}:{int(suggested_price)}"),
                                        InlineKeyboardButton("✏️ Своя цена", callback_data=f"set_custom_price:{product['id']}")
                                    ],
                                    [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_price:{product['id']}")]
                                ]
                                await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
                        except Exception as e:
                            logger.error(f"Our_price calculation error: {str(e)}")

                    # Магазин/Базар/Лавка → алерты
                    else:
                        try:
                            our_price = product.get("our_price")
                            if our_price:
                                alerts = await check_alerts(product["id"], source_to_write, item.price, our_price, old_price=old_price_for_alert)
                                if alerts:
                                    for alert in alerts:
                                        await query.message.reply_text(alert)
                        except Exception as e:
                            logger.error(f"Alert check error: {str(e)}")

                except Exception as e:
                    logger.error(f"Insert error for {item.product}: {str(e)}")
                    await query.message.reply_text(f"⚠️ Ошибка при записи {item.product}")
                    return None

            # Send new message with all confirmations (instead of editing to avoid conflicts)
            final_message = "\n".join(confirmations)
            await query.message.reply_text(final_message)

            del sessions[session_id]
            # Очищаем pending_session_id из user_data
            if "pending_session_id" in context.user_data:
                del context.user_data["pending_session_id"]
            return None

        except Exception as e:
            logger.error(f"Callback confirm error: {str(e)}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка: {str(e)[:100]}")
            return None

    elif action == "confirm_edit":
        await query.edit_message_text("Слушаю исправление.")
        del sessions[session_id]
        return None

    elif action == "confirm_cancel":
        await query.edit_message_text("✖ Принято, отставить.")
        del sessions[session_id]
        return None


    # Handle source selection for photo, text, or voice (callback_data = "source:{source_id}")
    elif action == "source":
        source_id = session_id  # For "source:magazin", session_id will be "magazin"
        logger.info(f"Source callback: source_id={source_id}, pending_photo={context.user_data.get('pending_photo')}, pending_text={context.user_data.get('pending_text_item')}, pending_voice_session={context.user_data.get('pending_voice_session')}")

        # Check if this is for voice (incomplete session with missing source)
        if "pending_voice_session" in context.user_data:
            voice_session_id = context.user_data["pending_voice_session"]
            if voice_session_id in sessions:
                voice_session = sessions[voice_session_id]
                # Update source in existing items
                for item in voice_session.items:
                    item.source = source_id
                voice_session.missing_field = None
                # Show confirmation
                from models import ParsedResult
                parsed = ParsedResult(source=source_id, items=voice_session.items, language=voice_session.language)
                message, markup = await create_confirmation_message(parsed, language=voice_session.language)
                await query.message.reply_text(message, reply_markup=markup)
                del context.user_data["pending_voice_session"]
                return None

        # Check if this is for photo
        if "pending_photo" in context.user_data:
            parsed = context.user_data["pending_photo"]
            parsed.source = source_id
            await query.edit_message_text("⏳ Обрабатываю...")
            message, markup = await create_confirmation_message(parsed)
            await query.message.reply_text(message, reply_markup=markup)
            del context.user_data["pending_photo"]
            return None

        # Check if this is for text
        if "pending_text_item" in context.user_data:
            item_data = context.user_data["pending_text_item"]
            try:
                await insert_snapshot(
                    item_data["product_id"],
                    source_id,
                    item_data["price"],
                    item_data["unit"],
                    item_data["text"]
                )

                source_name = get_source_display_name(source_id)
                product = await get_product_by_name(item_data.get("product_name", ""))
                product_name = product["name"].capitalize() if product else "Товар"

                await query.edit_message_text(
                    f"✅ Записал: {product_name} — {item_data['price']:,.0f} ₸/{item_data['unit']} ({source_name})"
                )
                del context.user_data["pending_text_item"]
            except Exception as e:
                logger.error(f"Text item insert error: {str(e)}")
                await query.edit_message_text(f"❌ Ошибка: {str(e)[:100]}")
            return None

def get_session(session_id: str) -> Session:
    """Retrieve session by ID."""
    return sessions.get(session_id)

def remove_session(session_id: str):
    """Remove expired session."""
    if session_id in sessions:
        del sessions[session_id]

def cleanup_expired_sessions():
    """Remove all expired sessions."""
    expired = [sid for sid, s in sessions.items() if s.is_expired()]
    for sid in expired:
        del sessions[sid]
