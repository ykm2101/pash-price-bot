from services.supabase import insert_alert, get_latest_price_by_source
from typing import List, Optional

async def check_alerts(product_id: int, source: str, new_price: float, our_price: float, old_price: Optional[float] = None) -> List[str]:
    """
    Check for price alerts and return alert messages.
    old_price — предыдущая цена конкурента (должна быть получена ДО insert_snapshot).
    Если не передана — пробуем получить из БД (может быть уже перезаписана).
    """
    alerts = []

    try:
        # Если old_price не передан — берём из БД (актуально только если вызов ДО insert)
        if old_price is None:
            prev = await get_latest_price_by_source(product_id, source)
            old_price = prev["price"] if prev else None

        # Порог изменения: для оптовой (altyn_orda) = 5%, для конкурентов = 10%
        threshold = 0.05 if source == "altyn_orda" else 0.10

        # 1. Цена изменилась vs предыдущая
        if old_price and old_price != new_price:
            price_change = (old_price - new_price) / old_price

            if price_change > threshold:
                if source == "altyn_orda":
                    message = f"📉 Оптовая цена снизилась: {old_price:,.0f}₸ → {new_price:,.0f}₸ (-{price_change*100:.1f}%) — пересмотри нашу цену"
                else:
                    message = f"📉 {source}: цена снизилась {old_price:,.0f}₸ → {new_price:,.0f}₸ (-{price_change*100:.1f}%)"
                await insert_alert(product_id, "price_drop", message)
                alerts.append(message)

            elif price_change < -threshold:
                if source == "altyn_orda":
                    message = f"📈 Оптовая цена выросла: {old_price:,.0f}₸ → {new_price:,.0f}₸ (+{abs(price_change)*100:.1f}%) — пересмотри нашу цену"
                else:
                    message = f"📈 {source}: цена выросла {old_price:,.0f}₸ → {new_price:,.0f}₸ (+{abs(price_change)*100:.1f}%)"
                await insert_alert(product_id, "price_spike", message)
                alerts.append(message)

        # 2. Для конкурентов: разрыв с нашей ценой стал маленьким (< 15%) — опасно
        if our_price and source != "altyn_orda":
            gap = (new_price - our_price) / our_price
            if -0.15 < gap < 0.15:
                message = f"⚠️ Цена {source} ({new_price:,.0f}₸) близка к нашей ({our_price:,.0f}₸) — разрыв {gap*100:.1f}%"
                await insert_alert(product_id, "gap_shrink", message)
                alerts.append(message)

    except Exception as e:
        print(f"Error checking alerts: {str(e)}")

    return alerts
