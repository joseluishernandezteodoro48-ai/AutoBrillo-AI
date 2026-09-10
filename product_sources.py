"""Fuentes de productos para Brillo."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from connectors.mercadolibre_api import MercadoLibreAPI


class ProductSourceError(RuntimeError):
    pass


class MercadoLibreSource:
    """Descubrimiento de candidatos desde el marketplace público de Mercado Libre."""

    def __init__(self, api: MercadoLibreAPI | None = None):
        self.api = api or MercadoLibreAPI()

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = str(query).strip()
        if not query:
            raise ValueError("query requerido")
        limit = max(1, min(int(limit), 20))
        try:
            data = self.api.search(query, limit)
        except Exception as exc:
            raise ProductSourceError(str(exc)) from exc

        products: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            # /sites/{site}/search devuelve publicaciones: title/price/permalink.
            # No confundir estos datos con costo de proveedor.
            name = str(item.get("title") or item.get("name") or "").strip()
            price = float(item.get("price") or 0)
            if not name or price <= 0:
                continue
            products.append({
                "name": name,
                "price": price,
                "cost": 0.0,
                "commission": 0.0,
                "url": item.get("permalink", ""),
                "active": str(item.get("status", "active")) == "active",
                "score": float(item.get("sold_quantity") or 0),
                "source": "mercadolibre",
                "source_id": item.get("id", ""),
                "cost_known": False,
                "marketplace_price_known": True,
                "currency_id": item.get("currency_id", "MXN"),
                "buy_box_item_id": item.get("id", ""),
                "seller_id": item.get("seller", {}).get("id", "") if isinstance(item.get("seller"), dict) else "",
            })
        return products


def search_products(query: str, limit: int = 10, source: str | None = None) -> List[Dict[str, Any]]:
    """Selecciona la fuente configurada; por defecto usa Mercado Libre."""
    selected = (source or os.getenv("AUTOBRILLO_PRODUCT_SOURCE", "mercadolibre")).lower()
    if selected == "mercadolibre":
        return MercadoLibreSource().search(query, limit)
    raise ProductSourceError(f"Fuente no soportada: {selected}")
