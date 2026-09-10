"""Fuentes de productos para Brillo."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from connectors.mercadolibre_api import MercadoLibreAPI


class ProductSourceError(RuntimeError):
    pass


class MercadoLibreSource:
    """Descubrimiento de candidatos mediante el catálogo autenticado de Mercado Libre."""

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
            winner = item.get("buy_box_winner") or {}
            price = float(winner.get("price") or 0)
            products.append({
                "name": str(item.get("name") or item.get("family_name") or "").strip(),
                "price": price,
                "cost": 0.0,
                "commission": 0.0,
                "url": item.get("permalink", ""),
                "active": str(item.get("status", "active")) == "active",
                "score": float(item.get("sold_quantity") or 0),
                "source": "mercadolibre",
                "source_id": item.get("id", ""),
                "cost_known": False,
                "marketplace_price_known": price > 0,
                "currency_id": winner.get("currency_id", "MXN"),
                "buy_box_item_id": winner.get("item_id", ""),
                "seller_id": winner.get("seller_id", ""),
            })
        return products


def search_products(query: str, limit: int = 10, source: str | None = None) -> List[Dict[str, Any]]:
    """Selecciona la fuente configurada; por defecto usa Mercado Libre."""
    selected = (source or os.getenv("AUTOBRILLO_PRODUCT_SOURCE", "mercadolibre")).lower()
    if selected == "mercadolibre":
        return MercadoLibreSource().search(query, limit)
    raise ProductSourceError(f"Fuente no soportada: {selected}")
