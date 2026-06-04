from supabase import create_client
from config import SUPABASE_URL, SUPABASE_ANON_KEY
from models import PriceEntry
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    logger.info(f"Supabase connected: {SUPABASE_URL}")
except Exception as e:
    logger.error(f"Supabase init failed: {e}")
    supabase = None

async def insert_snapshot(product_id: int, source: str, price: float, unit: str,
                          raw_input: str = None, source_detail: str = None) -> bool:
    """Insert price snapshot into database."""
    try:
        row = {
            "product_id": product_id,
            "source": source,
            "price": price,
            "unit": unit,
            "raw_input": raw_input,
            "recorded_at": datetime.utcnow().isoformat()
        }
        if source_detail:
            row["source_detail"] = source_detail
        supabase.table("price_snapshots").insert(row).execute()
        return True
    except Exception as e:
        raise Exception(f"Failed to insert snapshot: {str(e)}")

async def get_product_by_name(product_name: str) -> dict:
    """Get product by name or alias."""
    try:
        response = supabase.table("products").select("*").execute()
        products = response.data
        
        product_lower = product_name.lower()
        for product in products:
            if product["name"].lower() == product_lower:
                return product
            
            aliases = product.get("name_aliases", [])
            if aliases and product_lower in [a.lower() for a in aliases]:
                return product
        
        return None
    except Exception as e:
        raise Exception(f"Failed to get product: {str(e)}")

async def get_or_create_product(product_name: str, default_markup: int = None) -> tuple:
    """Get product by name, or create it if not found. Returns (product, created).
    markup_pct задаётся только для товаров с Алтын-Орды (оптовые).
    Для магазина/базара/лавки — markup_pct=None (просто отслеживаем цены).
    """
    try:
        product = await get_product_by_name(product_name)
        if product:
            return product, False

        name = product_name.lower().strip()
        response = supabase.table("products").insert({
            "name": name,
            "unit": "кг",
            "markup_pct": default_markup,
            "our_price": None,
            "container_weights": {}
        }).execute()
        new_product = response.data[0] if response.data else None
        markup_info = f"markup={default_markup}%" if default_markup else "без наценки"
        logger.info(f"Auto-created product: {name} ({markup_info})")
        return new_product, True
    except Exception as e:
        raise Exception(f"Failed to get or create product: {str(e)}")

async def get_latest_prices() -> list:
    """Get latest price snapshots for report."""
    try:
        response = supabase.table("price_snapshots").select("*").order("recorded_at", desc=True).limit(100).execute()
        return response.data
    except Exception as e:
        raise Exception(f"Failed to get prices: {str(e)}")

async def insert_alert(product_id: int, alert_type: str, message: str) -> bool:
    """Insert alert into database."""
    try:
        supabase.table("alerts").insert({
            "product_id": product_id,
            "type": alert_type,
            "message": message,
            "seen": False,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return True
    except Exception as e:
        raise Exception(f"Failed to insert alert: {str(e)}")

async def get_unseen_alerts() -> list:
    """Get unseen alerts."""
    try:
        response = supabase.table("alerts").select("*").eq("seen", False).execute()
        return response.data
    except Exception as e:
        raise Exception(f"Failed to get alerts: {str(e)}")

async def mark_alerts_seen(alert_ids: list) -> bool:
    """Mark alerts as seen."""
    try:
        for alert_id in alert_ids:
            supabase.table("alerts").update({"seen": True}).eq("id", alert_id).execute()
        return True
    except Exception as e:
        raise Exception(f"Failed to mark alerts seen: {str(e)}")

async def update_our_price(product_id: int, price: float) -> bool:
    """Update our_price for product."""
    try:
        supabase.table("products").update({"our_price": price}).eq("id", product_id).execute()
        logger.info(f"Updated our_price for product {product_id}: {price}")
        return True
    except Exception as e:
        raise Exception(f"Failed to update our_price: {str(e)}")

async def get_product_with_markup(product_id: int) -> dict:
    """Get product with markup_pct."""
    try:
        response = supabase.table("products").select("id, name, our_price, markup_pct").eq("id", product_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        raise Exception(f"Failed to get product with markup: {str(e)}")

async def get_container_weight(product_id: int, container: str) -> float:
    """Get stored weight for container type (e.g. ящик → 18.0 kg)."""
    try:
        response = supabase.table("products").select("container_weights").eq("id", product_id).execute()
        if response.data:
            weights = response.data[0].get("container_weights") or {}
            return weights.get(container)
        return None
    except Exception as e:
        logger.error(f"Failed to get container weight: {str(e)}")
        return None

async def save_container_weight(product_id: int, container: str, weight_kg: float) -> bool:
    """Save container weight for future use."""
    try:
        response = supabase.table("products").select("container_weights").eq("id", product_id).execute()
        weights = {}
        if response.data:
            weights = response.data[0].get("container_weights") or {}
        weights[container] = weight_kg
        supabase.table("products").update({"container_weights": weights}).eq("id", product_id).execute()
        logger.info(f"Saved container weight: product={product_id}, {container}={weight_kg}кг")
        return True
    except Exception as e:
        logger.error(f"Failed to save container weight: {str(e)}")
        return False

async def insert_wholesale_lot(product_id: int, container: str, container_price: float,
                               weight_kg: float, price_per_kg: float, our_price: float,
                               raw_input: str = None) -> bool:
    """Insert raw wholesale lot data (Altyn-Orda)."""
    try:
        supabase.table("wholesale_lots").insert({
            "product_id": product_id,
            "container": container,
            "container_price": container_price,
            "weight_kg": weight_kg,
            "price_per_kg": price_per_kg,
            "our_price": our_price,
            "raw_input": raw_input,
            "recorded_at": datetime.utcnow().isoformat()
        }).execute()
        logger.info(f"Wholesale lot saved: product={product_id}, {container_price}₸/{container} ({weight_kg}кг) → {price_per_kg}₸/кг")
        return True
    except Exception as e:
        logger.error(f"Failed to insert wholesale lot: {str(e)}")
        return False

async def get_latest_wholesale_lot(product_id: int) -> dict:
    """Get latest wholesale lot for product."""
    try:
        response = supabase.table("wholesale_lots").select("*").eq("product_id", product_id).order("recorded_at", desc=True).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Failed to get wholesale lot: {str(e)}")
        return None

async def get_latest_price_by_source(product_id: int, source: str) -> dict:
    """Get latest price snapshot for product from specific source."""
    try:
        response = supabase.table("price_snapshots").select("*").eq("product_id", product_id).eq("source", source).order("recorded_at", desc=True).limit(1).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        raise Exception(f"Failed to get latest price: {str(e)}")
