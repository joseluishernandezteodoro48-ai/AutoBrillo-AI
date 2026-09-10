"""Fuentes de productos para Brillo.

La búsqueda de Mercado Libre se realiza mediante el cliente autenticado
para respetar OAuth y los permisos de la aplicación.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from connectors.mercadolibre_api import MercadoLibreAPI


class ProductSourceError(RuntimeError):
    pass


class MercadoLibreSource:
    """Descubrimiento de candidatos mediante la API autenticada de Mercado Libre."""

    def __init__(self, api: MercadoLibreAPI | None = None):
        self.api = api or MercadoLibreAPI()

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = str(query).strip()
        if not query:
            raise ValueError("query requerido")
        limit = max(1, min(int(limit), 50))
        try:
            data = self.api.search(query, limit)
        except Exception as exc:
            raise ProductSourceError(str(exc)) from exc

        products: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            price = float(item.get("price") or 0)
            products.append({
                "name": str(item.get("title") or "").strip(),
                "price": price,
                "cost": 0.0,
                "commission": 0.0,
                "url": item.get("permalink", ""),
                "active": True,
                "score": 0.0,
                "source": "mercadolibre",
                "source_id": item.get("id", ""),
            })
        return products


def search_products(query: str, limit: int = 10, source: str | None = None) -> List[Dict[str, Any]]:
    """Selecciona la fuente configurada; por defecto usa Mercado Libre autenticado."""
    selected = (source or os.getenv("AUTOBRILLO_PRODUCT_SOURCE", "mercadolibre")).lower()
    if selected == "mercadolibre":
        return MercadoLibreSource().search(query, limit)
    raise ProductSourceError(f"Fuente no soportada: {selected}")
