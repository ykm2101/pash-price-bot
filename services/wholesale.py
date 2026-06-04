"""
Логика пересчёта оптовых цен (Алтын-Орда) в розничные (за кг/шт).
"""
from services.supabase import get_container_weight, save_container_weight
import logging

logger = logging.getLogger(__name__)

CONTAINER_ALIASES = {
    "ящик": "ящик",
    "ящике": "ящик",
    "ящиков": "ящик",
    "мешок": "мешок",
    "мешке": "мешок",
    "мешков": "мешок",
    "коробка": "коробка",
    "коробке": "коробка",
    "коробок": "коробка",
    "поддон": "поддон",
    "поддоне": "поддон",
}

def normalize_container(text: str) -> str:
    """Normalize container name to canonical form."""
    if not text:
        return None
    return CONTAINER_ALIASES.get(text.lower().strip(), text.lower().strip())


async def resolve_price_per_kg(product_id: int, item) -> tuple:
    """
    Try to resolve price-per-kg from wholesale item.

    Returns (price_per_kg, weight_used, needs_weight_input)
    - price_per_kg: float if resolved, None if not
    - weight_used: float weight that was used
    - needs_weight_input: True if user needs to provide weight
    """
    container = normalize_container(item.container)
    if not container:
        # No container — treat price as already per-kg
        return item.price, None, False

    weight = item.container_weight_kg

    # If weight not provided by user — look up from DB
    if not weight:
        weight = await get_container_weight(product_id, container)

    if weight and weight > 0:
        price_per_kg = round(item.price / weight, 1)
        # Save weight to DB for future use (if it came from user input)
        if item.container_weight_kg:
            await save_container_weight(product_id, container, weight)
        return price_per_kg, weight, False
    else:
        # Need user to provide weight
        return None, None, True


def format_conversion_note(container_price: float, container: str, weight_kg: float, price_per_kg: float) -> str:
    """Format human-readable conversion note."""
    return f"📦 {container_price:,.0f}₸/{container} ÷ {weight_kg}кг = {price_per_kg:,.1f}₸/кг"
