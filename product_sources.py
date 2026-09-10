"""Fuentes de productos para Brillo.

La búsqueda pública de Mercado Libre se usa solo para descubrir candidatos.
No compra, publica ni cobra automáticamente.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List


class ProductSourceError(RuntimeError):
    pass


class MercadoLibreSource:
    """Descubrimiento de candidatos mediante el endpoint público de búsqueda."""

    BASE = "https://api.mercadolibre.com/sites/MLM/search"

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = str(query).strip()
        if not query:
            raise ValueError("query requerido")
        limit = max(1, min(int(limit), 50))
        params = urllib.parse.urlencode({"q": query, "limit": limit})
        request = urllib.request.Request(
            f"{self.BASE}?{params}",
            headers={"User-Agent": "AutoBrillo-AI/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProductSourceError(f"No se pudo consultar Mercado Libre: {exc}") from exc

        products: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            price = float(item.get("price") or 0)
            products.append({
                "name": item.get("title", "").strip(),
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
    """Selecciona la fuente configurada; por defecto usa Mercado Libre."""
    selected = (source or os.getenv("AUTOBRILLO_PRODUCT_SOURCE", "mercadolibre")).lower()
    if selected == "mercadolibre":
        return MercadoLibreSource().search(query, limit)
    raise ProductSourceError(f"Fuente no soportada: {selected}")
