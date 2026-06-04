from dataclasses import dataclass, field
from typing import Optional, List
from uuid import uuid4

@dataclass
class PriceEntry:
    product: str
    price: float
    unit: str
    source: Optional[str] = None
    source_detail: Optional[str] = None      # конкретный магазин: "magnum", "treds", "green_bazar"...
    container: Optional[str] = None          # "ящик" / "мешок" / "коробка" — только для altyn_orda
    container_weight_kg: Optional[float] = None

@dataclass
class ParsedResult:
    source: Optional[str]
    items: List[PriceEntry]
    language: str = "ru"
    source_detail: Optional[str] = None

@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    items: List[PriceEntry] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: __import__('time').time())
    language: str = "ru"  # 'ru', 'kk' (Kazakh), or 'mixed'
    missing_field: Optional[str] = None
    incomplete_item: Optional[PriceEntry] = None

    # Partial dialog state — что уже понятно, что ещё нет
    partial: dict = field(default_factory=dict)
    # Keys: product, price, unit, source, container, container_weight_kg
    # last_reminded_at: float — для таймаута напоминания
    last_reminded_at: Optional[float] = None

    def is_expired(self, ttl_seconds: int = 900) -> bool:
        import time
        return time.time() - self.created_at > ttl_seconds

    def is_partial_complete(self) -> bool:
        """True когда все обязательные поля заполнены."""
        p = self.partial
        if not p.get('product') or not p.get('price') or not p.get('source'):
            return False
        if p.get('source') == 'altyn_orda' and not p.get('container'):
            return False
        return True

    def next_missing(self) -> Optional[str]:
        """Возвращает имя следующего незаполненного поля."""
        p = self.partial
        if not p.get('product'):   return 'product'
        if not p.get('price'):     return 'price'
        if not p.get('source'):    return 'source'
        if p.get('source') == 'altyn_orda' and not p.get('container'):
            return 'container'
        return None
