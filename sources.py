SOURCE_MAP = {
    "magazin": {
        "display": "Магазин",
        "emoji": "🏪",
        "aliases": {
            # alias → source_detail key
            "магазин": None, "маркет": None, "гипермаркет": None,
            "супермаркет": None, "интернет": None, "онлайн": None,
            "market": None, "supermarket": None, "hypermarket": None,
            "online": None, "internet": None, "shop": None,
            "дүкен": None, "дукен": None,
            # конкретные магазины → detail
            "магнум": "magnum", "magnum": "magnum",
            "арбуз": "arbuz",   "arbuz": "arbuz",
            "тоймарт": "toymart", "toymart": "toymart",
            "галмарт": "galmart", "galmart": "galmart",
        }
    },
    "bazar": {
        "display": "Базар",
        "emoji": "🛒",
        "aliases": {
            "базар": None, "рынок": None, "барахолка": None,
            "bazar": None, "bazaar": None, "rynok": None,
            "нарық": None, "нарык": None,
            # конкретные базары → detail
            "зеленый базар": "green_bazar", "зелёный базар": "green_bazar",
            "зеленый": "green_bazar",       "зелёный": "green_bazar",
            "zelyony": "green_bazar",       "green bazaar": "green_bazar",
        }
    },
    "lavka": {
        "display": "Лавка",
        "emoji": "🥬",
        "aliases": {
            "лавка": None, "палатка": None, "ларёк": None, "ларек": None,
            "мини-маркет": None, "kiosk": None,
            "дүңгіршек": None, "дунгиршек": None,
            "lavka": None,
            # конкретные лавки → detail
            "тредс": "treds",      "treds": "treds",
            "тредз": "treds",      "tredz": "treds",
            "овощная": "ovoshnaya_lavka",
            "овощная лавка": "ovoshnaya_lavka",
        }
    },
    "altyn_orda": {
        "display": "Алтын-Орда",
        "emoji": "🏛",
        "aliases": {
            "алтын-орда": None, "алтын орда": None, "алтынорда": None,
            "алтын": None,
            "альтын-орда": None, "альтын орда": None, "альтынорда": None,
            "альтын": None,
            "оптовка": None, "опт": None, "оптовый": None,
            "altyn orda": None, "altyn-orda": None, "altynorda": None,
            "altyn": None, "wholesale": None, "opt": None,
        }
    }
}

SOURCE_LIST = list(SOURCE_MAP.keys())
SOURCE_NAMES = [SOURCE_MAP[s]["display"] for s in SOURCE_LIST]


def get_source_by_alias(text: str) -> tuple:
    """Match source by alias. Returns (source_id, source_detail).
    source_detail — конкретное название (magnum, treds, ...) или None если выбрана категория.
    """
    text_lower = text.lower().strip()

    for source_id, source_data in SOURCE_MAP.items():
        # Точное совпадение с display name или ключом → категория без detail
        if source_data["display"].lower() == text_lower or source_id.lower() == text_lower:
            return source_id, None

        aliases = source_data["aliases"]
        if text_lower in aliases:
            return source_id, aliases[text_lower]

    return None, None


def get_source_display_name(source_id: str) -> str:
    """Get display name for source ID."""
    if source_id in SOURCE_MAP:
        return SOURCE_MAP[source_id]["display"]
    return source_id


def get_source_emoji(source_id: str) -> str:
    """Get emoji for source ID."""
    if source_id in SOURCE_MAP:
        return SOURCE_MAP[source_id]["emoji"]
    return "📍"
