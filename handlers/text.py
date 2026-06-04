from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.gemini import parse_free_text
from services.supabase import get_product_by_name, get_or_create_product, insert_snapshot, get_latest_prices, get_unseen_alerts, mark_alerts_seen, get_latest_price_by_source, insert_wholesale_lot, get_latest_wholesale_lot, supabase
from services.alerts import check_alerts
from services.wholesale import resolve_price_per_kg, format_conversion_note, normalize_container
from handlers.confirm import create_confirmation_message
from sources import get_source_by_alias, SOURCE_MAP, SOURCE_LIST, get_source_display_name
from datetime import datetime, timedelta
import logging
import re

logger = logging.getLogger(__name__)

async def handle_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /price command."""
    try:
        args = " ".join(context.args).strip()
        if not args:
            await update.message.reply_text("Формат: /price <товар> <цена> [источник]")
            return

        parts = args.split()
        if len(parts) < 2:
            await update.message.reply_text("Минимум: /price <товар> <цена>")
            return

        product_name = parts[0]
        try:
            price = float(parts[1])
        except ValueError:
            await update.message.reply_text("Цена должна быть числом")
            return

        source = None
        source_detail = None
        if len(parts) > 2:
            source_text = " ".join(parts[2:])
            source, source_detail = get_source_by_alias(source_text)
            if not source:
                await update.message.reply_text(f'Неизвестный источник: "{source_text}". Доступные: магнум, тредс, базар, лавка, альтын-орда')
                return
        else:
            # No source specified - ask user
            buttons = [
                [
                    InlineKeyboardButton(f"{SOURCE_MAP[k]['emoji']} {SOURCE_MAP[k]['display']}", callback_data=f"source:{k}")
                    for k in SOURCE_LIST
                ]
            ]
            await update.message.reply_text("Откуда это цена?", reply_markup=InlineKeyboardMarkup(buttons))
            context.user_data["pending_text_item"] = {
                "product_id": product["id"],
                "product_name": product["name"],
                "price": price,
                "unit": "кг",
                "text": args
            }
            return
        unit = "кг"

        try:
            is_wholesale = (source == "altyn_orda")
            product, created = await get_or_create_product(product_name, default_markup=25 if is_wholesale else None)
            if created:
                info = "наценка 25%" if is_wholesale else "без наценки"
                await update.message.reply_text(f'➕ Добавил новый товар: {product_name} ({info})')
        except Exception as e:
            logger.error(f"Supabase error: {str(e)}")
            await update.message.reply_text("⚠️ База данных недоступна. Проверь SUPABASE_URL в .env")
            return

        try:
            await insert_snapshot(product["id"], source or "manual", price, unit, args,
                                  source_detail=source_detail)
        except Exception as e:
            logger.error(f"Insert error: {str(e)}")
            await update.message.reply_text("⚠️ Ошибка при записи в БД")
            return

        await update.message.reply_text(f"✅ Записал: {product['name'].capitalize()} — {price:,.0f} ₸/{unit}" +
                                       (f" ({source})" if source else ""))

    except Exception as e:
        logger.error(f"Price command error: {str(e)}")
        await update.message.reply_text("⚠️ Неожиданная ошибка. Проверь логи.")

async def handle_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /report command - show price comparison."""
    try:
        all_products_response = supabase.table("products").select("id, name, our_price").execute()
        products = all_products_response.data

        if not products:
            await update.message.reply_text("Нет товаров в справочнике")
            return

        today = datetime.now().strftime("%d.%m")
        lines = [f"📊 Сводка цен — {today}\n"]

        has_data = False

        for product in products:
            our_price = product.get("our_price")

            # Get latest prices by category
            altyn = await get_latest_price_by_source(product["id"], "altyn_orda")
            magazin = await get_latest_price_by_source(product["id"], "magazin")
            bazar = await get_latest_price_by_source(product["id"], "bazar")
            wholesale = await get_latest_wholesale_lot(product["id"])

            lavka = await get_latest_price_by_source(product["id"], "lavka")

            # Skip products with no data at all
            if not our_price and not altyn and not magazin and not bazar and not lavka and not wholesale:
                continue

            has_data = True
            name = product["name"].capitalize()

            our_str   = f"{our_price:,.0f}₸"        if our_price else "—"
            altyn_str = f"{altyn['price']:,.0f}₸"   if altyn     else "—"
            mag_str   = f"{magazin['price']:,.0f}₸"  if magazin   else "—"
            bazar_str = f"{bazar['price']:,.0f}₸"   if bazar     else "—"
            lavka_str = f"{lavka['price']:,.0f}₸"   if lavka     else "—"

            # Разница: наша цена vs магазин
            # pct > 0 = магазин дороже нас = хорошо (🟢)
            # pct < 0 = магазин дешевле нас = плохо (🔴)
            diff_str = ""
            if our_price and magazin:
                diff = magazin["price"] - our_price
                pct = (diff / our_price) * 100
                if pct > 5:
                    diff_str = f" 🟢 Мы дешевле на {pct:.0f}%"
                elif pct < -5:
                    diff_str = f" 🔴 Магазин дешевле на {abs(pct):.0f}%"
                else:
                    diff_str = " ≈ одинаково"

            # Оптовые данные (ящик)
            wholesale_str = ""
            if wholesale:
                wholesale_str = (
                    f"\n  📦 {wholesale['container']} {wholesale['container_price']:,.0f}₸"
                    f" ({wholesale['weight_kg']}кг) → {wholesale['price_per_kg']:,.0f}₸/кг"
                )

            lines.append(
                f"*{name}*\n"
                f"  Пэш: {our_str} | Опт/кг: {altyn_str} | Магазин: {mag_str} | Лавка: {lavka_str} | Базар: {bazar_str}{diff_str}"
                f"{wholesale_str}"
            )

        if not has_data:
            await update.message.reply_text("Нет данных о ценах. Отправь первую цену голосом, фото или текстом.")
            return

        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Report command error: {str(e)}")
        await update.message.reply_text("⚠️ Ошибка при генерации отчёта")

async def handle_alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /alerts command - show unseen alerts."""
    try:
        alerts = await get_unseen_alerts()
        
        if not alerts:
            await update.message.reply_text("Нет новых алертов")
            return
        
        message = "🔔 Непросмотренные алерты:\n\n"
        for alert in alerts[:10]:  # Show max 10
            message += f"• {alert['message']}\n"
        
        await update.message.reply_text(message)
        
        alert_ids = [a["id"] for a in alerts]
        await mark_alerts_seen(alert_ids)
    
    except Exception as e:
        logger.error(f"Alerts command error: {str(e)}")
        await update.message.reply_text("⚠️ Ошибка при загрузке алертов")

async def handle_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    sources_text = "\n".join([f"  • {SOURCE_MAP[s]['display']}: магнум, арбуз, тоймарт, галмарт..." if s == "magazin"
                              else f"  • {SOURCE_MAP[s]['display']}: рынок, базар, зелёный базар..." if s == "bazar"
                              else f"  • {SOURCE_MAP[s]['display']}: лавка, тредс, овощная, палатка..." if s == "lavka"
                              else f"  • {SOURCE_MAP[s]['display']}: алтын-орда, оптовка, опт..."
                              for s in SOURCE_LIST])

    help_text = f"""📚 Доступные команды:

/price <товар> <цена> [источник] — Записать цену (сразу в БД)
/report — Утренняя сводка: наши цены vs конкуренты
/alerts — Показать непросмотренные алерты
/help — Эта справка

🏪 Категории источников:
{sources_text}

💬 Способы ввода:
• 🎤 Голосовое сообщение (РУССКИЙ, КАЗАХСКИЙ или СМЕШАННЫЙ)
• 📸 Фото ценников или скриншот приложения
• 📝 Текст командой /price или просто сообщением

📝 Примеры на русском:
/price банан 920 магнум
/price авокадо 1500 лавка
/price помидор 780 базар
"банан 920 магнум"
"895 авокадо базар"

🎤 Примеры голоса (русский):
"банан 920 магнум"
"авокадо тысяча пятьсот лавка"

🎤 Примеры голоса (казахский):
"банан тоғыс жүз жиырма магнум"
"қызанақ сегіз жүз базар"

🎤 Примеры смешанного языка:
"қызанақ 780 магнум"
"авокадо тысяча пятьсот базар"
"""
    await update.message.reply_text(help_text)

async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-form text input for price parsing."""
    from handlers.confirm import sessions, create_confirmation_message
    from handlers.dialog import ask_next, format_known, get_emoji
    from models import PriceEntry

    text = update.message.text.strip()

    if not text or len(text) < 1 or len(text) > 200:
        return

    # /cancel — сбросить partial состояние
    if text.lower() in ('/cancel', 'отмена', 'cancel'):
        pid = context.user_data.pop("partial_session_id", None)
        if pid and pid in sessions:
            del sessions[pid]
        context.user_data.pop("pending_weight", None)
        await update.message.reply_text("Отменено ✌️")
        return

    # CHECK: есть ли активный partial диалог?
    partial_session_id = context.user_data.get("partial_session_id")
    if partial_session_id and partial_session_id in sessions:
        session = sessions[partial_session_id]
        missing = session.next_missing()
        p = session.partial

        if missing == 'product':
            p['product'] = text.lower().strip()

        elif missing == 'price':
            try:
                price_val = float(text.replace(',', '.').replace(' ', ''))
                p['price'] = price_val
            except ValueError:
                await update.message.reply_text("Не поняла цену. Напиши число, например: 920")
                return

        elif missing == 'container':
            from services.wholesale import normalize_container
            container = normalize_container(text)
            p['container'] = container or text.lower().strip()

        # После заполнения поля — задать следующий вопрос или показать confirmation
        async def reply(msg, **kwargs):
            await update.message.reply_text(msg, **kwargs)

        await ask_next(session, reply)
        return

    # CHECK: ожидаем ли вес контейнера (или цену+вес) от пользователя?
    pending_weight = context.user_data.get("pending_weight")
    if pending_weight:
        try:
            # Режим "цена и вес" или "товар цена вес"
            if pending_weight.get("awaiting_price_and_weight"):
                parts = text.strip().split()
                needs_product = pending_weight.get("awaiting_product_too")

                if needs_product and len(parts) == 3:
                    # "банан 19000 19"
                    product_name_input = parts[0].lower()
                    container_price = float(parts[1].replace(",", "."))
                    weight_kg = float(parts[2].replace(",", ".").replace("кг", "").replace("кило", ""))
                    product = await get_product_by_name(product_name_input)
                    if not product:
                        await update.message.reply_text(f'❌ Не знаю товар "{product_name_input}". Напиши: товар цена вес')
                        return
                    pending_weight["product_id"] = product["id"]
                    pending_weight["product_name"] = product["name"]
                    pending_weight["markup_pct"] = product.get("markup_pct")
                    pending_weight["our_price"] = product.get("our_price")
                elif not needs_product and len(parts) == 2:
                    # "19000 19"
                    container_price = float(parts[0].replace(",", "."))
                    weight_kg = float(parts[1].replace(",", ".").replace("кг", "").replace("кило", ""))
                    # Если product_id ещё не известен — получить по имени
                    if not pending_weight.get("product_id") and pending_weight.get("product_name"):
                        product = await get_product_by_name(pending_weight["product_name"])
                        if product:
                            pending_weight["product_id"] = product["id"]
                            pending_weight["markup_pct"] = product.get("markup_pct")
                            pending_weight["our_price"] = product.get("our_price")
                else:
                    if needs_product:
                        await update.message.reply_text("❌ Напиши: товар цена вес\nНапример: банан 19000 19")
                    else:
                        await update.message.reply_text("❌ Напиши цену и вес через пробел\nНапример: 19000 19")
                    return
                pending_weight["container_price"] = container_price
                pending_weight["awaiting_price_and_weight"] = False
            else:
                weight_kg = float(text.replace(",", ".").replace("кг", "").replace("кило", "").strip())
                container_price = pending_weight["container_price"]

            if weight_kg <= 0:
                raise ValueError("weight must be positive")

            product_id = pending_weight["product_id"]
            product_name = pending_weight["product_name"]
            container_price = pending_weight.get("container_price") or container_price
            container = pending_weight["container"]
            unit = pending_weight["unit"]
            markup_pct = pending_weight.get("markup_pct")
            our_price = pending_weight.get("our_price")

            price_per_kg = round(container_price / weight_kg, 1)

            # Сохранить вес для будущего использования
            from services.supabase import save_container_weight, get_latest_price_by_source as glps
            await save_container_weight(product_id, container, weight_kg)

            # Записать пересчитанную цену
            conversion_note = format_conversion_note(container_price, container, weight_kg, price_per_kg)
            raw = f"{container_price}₸/{container} ({weight_kg}кг) → {price_per_kg}₸/кг"

            prev_snap = await glps(product_id, "altyn_orda")
            old_price_for_alert = prev_snap["price"] if prev_snap else None

            suggested_price = round(price_per_kg * (1 + (markup_pct or 25) / 100))
            await insert_snapshot(product_id, "altyn_orda", price_per_kg, unit, raw)
            await insert_wholesale_lot(product_id, container, container_price, weight_kg, price_per_kg, suggested_price, raw)
            del context.user_data["pending_weight"]

            await update.message.reply_text(
                f"✅ Записал: {product_name.capitalize()}\n{conversion_note}\n(Алтын-Орда)"
            )

            # Показать расчёт our_price
            if markup_pct:
                suggested_price = price_per_kg * (1 + markup_pct / 100)
                msg = f"💡 {price_per_kg:,.1f}₸/кг × +{markup_pct}% = {suggested_price:,.0f}₸/кг\n\nУстановить как нашу цену?"
                buttons = [
                    [
                        InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product_id}:{int(suggested_price)}"),
                        InlineKeyboardButton("✏️ Своя цена", callback_data=f"set_custom_price:{product_id}")
                    ],
                    [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_price:{product_id}")]
                ]
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

            # Алерты
            if our_price:
                alerts = await check_alerts(product_id, "altyn_orda", price_per_kg, our_price, old_price=old_price_for_alert)
                for alert in alerts:
                    await update.message.reply_text(alert)

        except ValueError:
            await update.message.reply_text("❌ Напиши число, например: 18")
        return

    # CHECK: есть ли pending session для интерактивного заполнения?
    pending_session_id = context.user_data.get("pending_session_id")
    logger.info(f"FREE TEXT: pending_session_id={pending_session_id}, in sessions={pending_session_id in sessions if pending_session_id else False}, user_data={context.user_data}")

    if pending_session_id and pending_session_id in sessions:
        logger.info(f"INTERACTIVE MODE: filling {pending_session_id}")
        session = sessions[pending_session_id]

        if text.lower() == "отмена":
            await update.message.reply_text("❌ Отмена. Попробуй ещё раз.")
            del sessions[pending_session_id]
            del context.user_data["pending_session_id"]
            return

        # Заполняем недостающее поле
        item = session.incomplete_item
        missing_field = session.missing_field

        if missing_field == "product":
            item.product = text.lower()
            session.missing_field = None  # Очищаем флаг
            # Проверяем есть ли ещё недостающие поля
            if not item.price or item.price <= 0:
                session.missing_field = "price"
                await update.message.reply_text("❓ Теперь напиши цену в тенге:")
                return
            elif not item.source:
                session.missing_field = "source"
                await update.message.reply_text("❓ Теперь напиши источник (магнум, тредс, арбуз и т.д.):")
                return

        elif missing_field == "price":
            try:
                item.price = float(text)
                session.missing_field = None
                if not item.source:
                    session.missing_field = "source"
                    await update.message.reply_text("❓ Теперь напиши источник:")
                    return
            except ValueError:
                await update.message.reply_text("❌ Это не число. Напиши цену цифрами:")
                return

        elif missing_field == "source":
            source_match, source_detail_match = get_source_by_alias(text)
            if source_match:
                item.source = source_match
                item.source_detail = source_detail_match
                session.missing_field = None
            else:
                await update.message.reply_text(f"❌ Не нашёл такой источник. Попробуй: магнум, тредс, арбуз, лавка, альтын-орда, тоймарт")
                return

        # Все поля заполнены → показать подтверждение
        if not session.missing_field:
            from models import ParsedResult
            from handlers.confirm import sessions

            pending_session_id = context.user_data.get("pending_session_id")
            # Используем существующую сессию, не создаём новую!
            session.items = [item]  # Обновляем items в существующей сессии
            sessions[pending_session_id] = session  # Обновляем в sessions

            # Теперь показываем confirmation с СУЩЕСТВУЮЩЕЙ сессией
            parsed = ParsedResult(source=item.source, items=[item], language=session.language)

            # Создаём сообщение без создания новой сессии
            source = parsed.source or ("Белгісіз" if session.language == "kk" else "Неизвестно")
            items_text = "\n".join([
                f"  {i.product.capitalize()} — {i.price:,.0f} ₸/{i.unit}"
                for i in parsed.items
            ])

            if session.language in ["kk", "mixed"]:
                message = f"""✅ Тану берілді ({source}):

{items_text}

Деректі базаға сақтау керек пе?"""
                buttons = [
                    [
                        InlineKeyboardButton("✅ Иә, сақтау", callback_data=f"confirm_yes:{pending_session_id}"),
                        InlineKeyboardButton("✏️ Түзету", callback_data=f"confirm_edit:{pending_session_id}")
                    ],
                    [InlineKeyboardButton("❌ Бас тарту", callback_data=f"confirm_cancel:{pending_session_id}")]
                ]
            else:
                message = f"""✅ Распознал ({source}):

{items_text}

Записать в базу?"""
                buttons = [
                    [
                        InlineKeyboardButton("✅ Да, записать", callback_data=f"confirm_yes:{pending_session_id}"),
                        InlineKeyboardButton("✏️ Исправить", callback_data=f"confirm_edit:{pending_session_id}")
                    ],
                    [InlineKeyboardButton("❌ Отмена", callback_data=f"confirm_cancel:{pending_session_id}")]
                ]

            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(buttons))
            del context.user_data["pending_session_id"]

        return

    try:
        parsed = await parse_free_text(text)

        if not parsed.items:
            # Попробовать вытащить цену и/или source из текста для partial диалога
            import re
            from handlers.dialog import ask_next
            from models import Session

            numbers = re.findall(r'\b\d{2,6}\b', text)
            price_guess = float(numbers[0]) if numbers else None
            top_source = parsed.source
            top_detail = getattr(parsed, 'source_detail', None)

            if price_guess or top_source:
                session = Session(language=parsed.language)
                session.partial = {
                    'product': None,
                    'price': price_guess,
                    'unit': 'кг',
                    'source': top_source,
                    'source_detail': top_detail,
                }
                sessions[session.session_id] = session
                context.user_data['partial_session_id'] = session.session_id

                async def reply_partial(msg, **kwargs):
                    await update.message.reply_text(msg, **kwargs)
                await ask_next(session, reply_partial)
            else:
                await update.message.reply_text("Не разобрал. Попробуй: банан 920 магнум")
            return

        for item in parsed.items:
            try:
                is_wholesale = (item.source == "altyn_orda")
                product, created = await get_or_create_product(item.product, default_markup=25 if is_wholesale else None)
                if created:
                    info = "наценка 25%" if is_wholesale else "без наценки"
                    await update.message.reply_text(f'➕ Добавил новый товар: {item.product} ({info})')

                # Use item.source, or fall back to top-level parsed.source
                effective_source = item.source or parsed.source
                if not effective_source:
                    # Partial dialog: знаем товар и цену, не знаем источник
                    from handlers.dialog import ask_next, get_emoji, format_known
                    from models import Session
                    session = Session(language=parsed.language)
                    session.partial = {
                        'product': item.product,
                        'price': item.price,
                        'unit': item.unit or 'кг',
                        'source': None,
                    }
                    sessions[session.session_id] = session
                    context.user_data['partial_session_id'] = session.session_id

                    async def reply(msg, **kwargs):
                        await update.message.reply_text(msg, **kwargs)
                    await ask_next(session, reply)
                    continue
                item.source = effective_source

                # === АЛТЫН-ОРДА: пересчёт оптовой цены в розничную ===
                # Триггер: container явный ИЛИ передан вес (напр. "12500 19кг")
                if not item.container and item.container_weight_kg:
                    item.container = "ящик"  # ящик по умолчанию если вес есть но контейнер не назван
                if item.source == "altyn_orda" and item.container:
                    container = normalize_container(item.container)
                    price_per_kg, weight_used, needs_weight = await resolve_price_per_kg(product["id"], item)

                    if needs_weight:
                        # Неизвестный вес → спросить пользователя
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
                        continue

                    # Вес известен → записать пересчитанную цену
                    conversion_note = format_conversion_note(item.price, container, weight_used, price_per_kg)
                    prev_snap = await get_latest_price_by_source(product["id"], "altyn_orda")
                    old_price_for_alert = prev_snap["price"] if prev_snap else None

                    raw = f"{item.price}₸/{container} ({weight_used}кг) → {price_per_kg}₸/кг"
                    await insert_snapshot(product["id"], "altyn_orda", price_per_kg, item.unit, raw)

                    source_name = get_source_display_name("altyn_orda")
                    await update.message.reply_text(
                        f"✅ Записал: {product['name'].capitalize()}\n"
                        f"{conversion_note}\n"
                        f"({source_name})"
                    )

                    # Алерты об изменении оптовой цены
                    our_price_val = product.get("our_price")
                    if our_price_val:
                        alerts = await check_alerts(product["id"], "altyn_orda", price_per_kg, our_price_val, old_price=old_price_for_alert)
                        for alert in alerts:
                            await update.message.reply_text(alert)

                    # Показать расчёт our_price
                    from services.supabase import get_product_with_markup
                    product_data = await get_product_with_markup(product["id"])
                    if product_data and product_data.get("markup_pct"):
                        markup_pct = product_data["markup_pct"]
                        suggested_price = price_per_kg * (1 + markup_pct / 100)
                        await insert_wholesale_lot(product["id"], container, item.price, weight_used, price_per_kg, round(suggested_price), raw)
                        msg = f"💡 {price_per_kg:,.1f}₸/кг × +{markup_pct}% = {suggested_price:,.0f}₸/кг\n\nУстановить как нашу цену?"
                        buttons = [
                            [
                                InlineKeyboardButton("✅ Да", callback_data=f"set_our_price:{product['id']}:{int(suggested_price)}"),
                                InlineKeyboardButton("✏️ Своя цена", callback_data=f"set_custom_price:{product['id']}")
                            ],
                            [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_price:{product['id']}")]
                        ]
                        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
                    continue

                # === ОБЫЧНАЯ ЦЕНА (магазин/базар/лавка или altyn_orda без контейнера) ===
                prev_snap = await get_latest_price_by_source(product["id"], item.source)
                old_price_for_alert = prev_snap["price"] if prev_snap else None

                await insert_snapshot(product["id"], item.source, item.price, item.unit, text,
                                      source_detail=getattr(item, 'source_detail', None))

                source_name = get_source_display_name(item.source)
                await update.message.reply_text(
                    f"✅ Записал: {product['name'].capitalize()} — {item.price:,.0f} ₸/{item.unit} ({source_name})"
                )

                if item.source == "altyn_orda":
                    from services.supabase import get_product_with_markup
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
                        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
                else:
                    our_price = product.get("our_price")
                    if our_price:
                        alerts = await check_alerts(product["id"], item.source, item.price, our_price, old_price=old_price_for_alert)
                        for alert in alerts:
                            await update.message.reply_text(alert)

            except Exception as e:
                logger.error(f"Insert error for {item.product}: {str(e)}")
                await update.message.reply_text(f"⚠️ Ошибка при записи {item.product}")

    except Exception as e:
        error_str = str(e)
        logger.error(f"Free text parsing error: {error_str}")

        if "429" in error_str or "quota" in error_str.lower():
            await update.message.reply_text("⚠️ Лимит API. Попробуй позже.")
        else:
            await update.message.reply_text("Не разобрал. Попробуй: банан 920 магнум")
