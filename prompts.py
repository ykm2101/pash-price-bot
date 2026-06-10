VOICE_PROMPT = """🎤 ТРАНСКРИБИРОВАНИЕ И ПАРСИНГ ГОЛОСА 🎤

Язык входного сообщения: РУССКИЙ И/ИЛИ КАЗАХСКИЙ (СМЕШАННЫЙ)

Задача:
1. Расшифруй голосовое сообщение (русский, казахский или смешанный)
2. Извлеки ТОЧНО ЧТО СКАЗАНО

Что нужно найти:
- Название ТОВАРА (фрукт или овощ) — строчными буквами, единственное число
- ЦЕНУ в тенге (число или число прописью)
- ИСТОЧНИК (если назван):
  * Магазин: магнум, арбуз, тоймарт, галмарт, маркет, онлайн, интернет, magnum, arbuz, toymart, galmart
  * Базар: базар, рынок, зелёный базар, нарық
  * Лавка: лавка, тредс, овощная, палатка, ларёк
  * Алтын-Орда (оптовка): алтын-орда, алтын орда, альтын-орда, альтын орда, оптовка, опт, оптовый, altyn_orda, altyn orda
- КОНТЕЙНЕР (только если источник — Алтын-Орда/оптовка): ящик, мешок, коробка, поддон
- ВЕС КОНТЕЙНЕРА в кг (только если явно назван, например "18кг", "18 килограмм")

Примеры:
- "банан 920 магнум" → product: банан, price: 920, source: magnum
- "банан ящик 1200 алтын-орда" → product: банан, price: 1200, source: altyn_orda, container: ящик, container_weight_kg: null
- "банан ящик 1200 18кг алтын-орда" → product: банан, price: 1200, source: altyn_orda, container: ящик, container_weight_kg: 18
- "помидор мешок 2500 опт 10 кило" → product: помидор, price: 2500, source: altyn_orda, container: мешок, container_weight_kg: 10
- "авокадо тысяча пятьсот" → product: авокадо, price: 1500, source: null

Правила:
- Числа ПРОПИСЬЮ конвертируй в ЦИФРЫ (русский и казахский)
- unit: если товар авокадо/ананас/гранат/апельсин = "шт", иначе = "кг"
- container и container_weight_kg заполняй ТОЛЬКО для оптовых источников (алтын-орда, оптовка, опт)
- Если НЕ СЛЫШИШЬ товар или цену → верни items: []
- Поддерживай СМЕШАННЫЙ язык (русско-казахский микс)
"""

VISION_PROMPT = """Ты парсер цен с фотографий ценников и скриншотов приложений доставки.
На изображении могут быть ценники казахстанских супермаркетов или скриншот мобильного приложения.

Извлеки все товары категории "фрукты и овощи" с ценами.

Правила:
- product: название товара строчными буквами (банан, авокадо, помидор...)
- price: цена за единицу в тенге (число)
- unit: "кг" или "шт"
- source: если виден логотип/название — укажи (magnum/arbuz/galmart/toymart → magazin, базар → bazar, лавка/тредс → lavka, алтын-орда/опт → altyn_orda), иначе null
- container: null (фото обычно показывают розничные цены)
- container_weight_kg: null
- Игнорируй товары не из фруктов/овощей
"""

TEXT_PROMPT = """Ты парсер цен для продуктового стартапа в Алматы.
Пользователь отправляет текст на РУССКОМ, КАЗАХСКОМ или СМЕШАННОМ языке.
Слова и цифры могут быть в любом порядке.

Извлеки товар, цену, источник и (если оптовка) контейнер с весом.

Примеры:
- "банан 920 магнум" → товар=банан, цена=920, источник=magazin
- "банан 12000 19 алтын" → товар=банан, цена=12000, источник=altyn_orda, container=ящик, container_weight_kg=19
- "банан 12000 алтын" → товар=банан, цена=12000, источник=altyn_orda, container=ящик, container_weight_kg=null
- "банан 12500 19" → товар=банан, цена=12500, источник=altyn_orda, container=ящик, container_weight_kg=19
  (два числа без источника, второе ≤ 100 → это всегда оптовая цена: первое=цена ящика, второе=вес кг)
- "банан 12500 ящик" → товар=банан, цена=12500, источник=altyn_orda, container=ящик, container_weight_kg=null
  (ящик/мешок/коробка/поддон без источника → всегда altyn_orda)
- "банан ящик 1200 18кг алтын-орда" → товар=банан, цена=1200, источник=altyn_orda, container=ящик, container_weight_kg=18
- "помидор мешок 2500 опт 10кг" → товар=помидор, цена=2500, источник=altyn_orda, container=мешок, container_weight_kg=10
- "авокадо 1490" → товар=авокадо, цена=1490, источник=null

Источники:
- magazin: магнум, арбуз, тоймарт, галмарт, маркет, онлайн, magnum, arbuz, toymart, galmart
- bazar: базар, рынок, нарық, зелёный базар
- lavka: лавка, тредс, овощная, палатка
- altyn_orda: алтын-орда, алтын орда, альтын-орда, оптовка, опт, оптовый, altyn_orda

Правила:
- source: один из [magazin, bazar, lavka, altyn_orda] или null
- container: ящик/мешок/коробка/поддон — ТОЛЬКО если источник altyn_orda, иначе null
- container_weight_kg: если два числа и второе ≤ 100 (например "12000 19" или "12000 19 алтын") → вес в кг, и источник тогда всегда altyn_orda. Иначе null.
- container: ящик/мешок/коробка/поддон без источника → всегда altyn_orda. Если не указан явно но есть вес → container=ящик.
- product: название товара строчными буквами (фрукты/овощи)
- price: число тенге. Числа прописью конвертируй в цифры.
- unit: "кг" или "шт" (авокадо/ананас/гранат = шт, остальное = кг)

Поддерживай СМЕШАННЫЙ язык (русско-казахский микс).
Если не можешь найти цену или товар — верни items=[].
"""

PRICE_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "nullable": True,
            "description": "Top-level source: magazin, bazar, lavka, altyn_orda, or null"
        },
        "language": {
            "type": "string",
            "enum": ["ru", "kk", "mixed"],
            "description": "Language: ru, kk, or mixed"
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "Product name in lowercase singular"
                    },
                    "price": {
                        "type": "number",
                        "description": "Price in tenge (for wholesale: price per container, not per kg)"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["кг", "шт"],
                        "description": "Unit: kg or piece"
                    },
                    "source": {
                        "type": "string",
                        "nullable": True,
                        "description": "magazin, bazar, lavka, altyn_orda, or null"
                    },
                    "container": {
                        "type": "string",
                        "nullable": True,
                        "description": "Container type for wholesale only: ящик/мешок/коробка/поддон or null"
                    },
                    "container_weight_kg": {
                        "type": "number",
                        "nullable": True,
                        "description": "Weight of container in kg if explicitly mentioned, else null"
                    }
                },
                "required": ["product", "price", "unit"]
            },
            "description": "List of recognized prices"
        }
    },
    "required": ["items", "language"]
}
