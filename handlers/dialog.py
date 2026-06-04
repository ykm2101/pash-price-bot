"""
Partial dialog logic — умный диалог с частичными данными.
Принцип: запомнить что поняли, переспросить только про дыры.
"""
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sources import SOURCE_MAP, SOURCE_LIST, get_source_display_name
from models import Session

# Эмодзи для товаров
PRODUCT_EMOJIS = {
    'банан': '🍌', 'бананы': '🍌',
    'яблоко': '🍎', 'яблоки': '🍎',
    'помидор': '🍅', 'помидоры': '🍅', 'томат': '🍅',
    'огурец': '🥒', 'огурцы': '🥒',
    'морковь': '🥕', 'морковка': '🥕',
    'авокадо': '🥑',
    'лимон': '🍋', 'лимоны': '🍋',
    'апельсин': '🍊', 'апельсины': '🍊',
    'мандарин': '🍊', 'мандарины': '🍊',
    'виноград': '🍇',
    'клубника': '🍓',
    'арбуз': '🍉',
    'дыня': '🍈',
    'манго': '🥭',
    'ананас': '🍍',
    'персик': '🍑', 'персики': '🍑',
    'нектарин': '🍑', 'нектарины': '🍑',
    'груша': '🍐', 'груши': '🍐',
    'вишня': '🍒', 'черешня': '🍒',
    'киви': '🥝',
    'гранат': '🍎', 'гранаты': '🍎',
    'голубика': '🫐', 'черника': '🫐',
    'малина': '🍓',
    'капуста': '🥬',
    'перец': '🌶',
    'баклажан': '🍆',
    'свёкла': '🫚', 'свекла': '🫚',
    'картофель': '🥔', 'картошка': '🥔',
    'лук': '🧅',
    'чеснок': '🧄',
    'шпинат': '🥬',
    'салат': '🥗',
}

def get_emoji(product: str) -> str:
    if not product:
        return '🛒'
    return PRODUCT_EMOJIS.get(product.lower().strip(), '🛒')

def format_known(partial: dict) -> str:
    """Формирует красивое описание того что уже известно.
    Пример: "🍌 Банан, 920 ₸ в Магнуме"
    """
    parts = []
    product = partial.get('product')
    price = partial.get('price')
    unit = partial.get('unit', 'кг')
    source = partial.get('source')
    container = partial.get('container')
    weight = partial.get('container_weight_kg')

    if product:
        emoji = get_emoji(product)
        parts.append(f"{emoji} {product.capitalize()}")

    if container and weight and price:
        parts.append(f"ящик {weight} кг, {price:,.0f} ₸")
        if source == 'altyn_orda':
            price_per_kg = price / weight
            parts.append(f"→ {price_per_kg:,.0f} ₸/кг")
    elif price:
        parts.append(f"{price:,.0f} ₸/{unit}")

    if source and source != 'altyn_orda':
        parts.append(f"в {get_source_display_name(source)}")
    elif source == 'altyn_orda':
        parts.append("с Алтын-Орды")

    return ", ".join(parts) if parts else "..."


def source_buttons(session_id: str, prefix: str = "partial_source") -> InlineKeyboardMarkup:
    """4 кнопки источника для partial dialog."""
    buttons = [
        [
            InlineKeyboardButton(
                f"{SOURCE_MAP[k]['emoji']} {SOURCE_MAP[k]['display']}",
                callback_data=f"{prefix}:{session_id}:{k}"
            )
            for k in SOURCE_LIST
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{session_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


def container_buttons(session_id: str) -> InlineKeyboardMarkup:
    """Кнопки типа контейнера."""
    containers = [("ящик", "📦"), ("коробка", "📫"), ("мешок", "🛍"), ("сетка", "🕸")]
    buttons = [
        [
            InlineKeyboardButton(f"{em} {c}", callback_data=f"partial_container:{session_id}:{c}")
            for c, em in containers
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{session_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


def unit_buttons(session_id: str) -> InlineKeyboardMarkup:
    """Кнопки единицы измерения."""
    buttons = [
        [
            InlineKeyboardButton("⚖️ кг", callback_data=f"partial_unit:{session_id}:кг"),
            InlineKeyboardButton("🔢 шт", callback_data=f"partial_unit:{session_id}:шт"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{session_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


def confirm_buttons(session_id: str) -> InlineKeyboardMarkup:
    """Кнопки подтверждения финального шага."""
    buttons = [
        [
            InlineKeyboardButton("✅ Записать", callback_data=f"partial_confirm:{session_id}"),
            InlineKeyboardButton("✏️ Исправить", callback_data=f"partial_edit:{session_id}"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{session_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


async def ask_next(session: Session, reply_func) -> bool:
    """Задать следующий вопрос по недостающему полю.
    Возвращает True если задан вопрос, False если всё заполнено.
    """
    missing = session.next_missing()
    known = format_known(session.partial)
    sid = session.session_id

    if not missing:
        # Всё заполнено — показать финальное подтверждение
        msg = f"{known}\n\nЗаписать?"
        await reply_func(msg, reply_markup=confirm_buttons(sid))
        return False  # больше вопросов нет

    session.last_reminded_at = None  # сбросить таймер напоминания

    if missing == 'product':
        await reply_func("А что за товар?",
                         reply_markup=InlineKeyboardMarkup([[
                             InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{sid}")
                         ]]))

    elif missing == 'price':
        prefix = f"{known}\n\n" if known != "..." else ""
        await reply_func(f"{prefix}Цена в тенге?",
                         reply_markup=InlineKeyboardMarkup([[
                             InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{sid}")
                         ]]))

    elif missing == 'source':
        prefix = f"{known}\n\n" if known != "..." else ""
        await reply_func(f"{prefix}Откуда цена?",
                         reply_markup=source_buttons(sid))

    elif missing == 'container':
        await reply_func(f"{known}\n\nЧто за упаковка?",
                         reply_markup=container_buttons(sid))

    return True  # вопрос задан


async def check_reminder(session: Session, reply_func):
    """Один раз напомнить если прошло 5 минут без ответа."""
    if session.last_reminded_at is not None:
        return  # уже напоминали
    age = time.time() - session.created_at
    if age > 300:  # 5 минут
        known = format_known(session.partial)
        session.last_reminded_at = time.time()
        await reply_func(
            f"Дописать про {known}? Или отмени — просто напиши /cancel",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"partial_cancel:{session.session_id}")
            ]])
        )
