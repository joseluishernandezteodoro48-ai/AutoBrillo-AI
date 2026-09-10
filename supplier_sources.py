"""Fuentes de proveedores para Tygo/Brillo.

Regla importante: una publicación de marketplace NO es un costo de proveedor.
Esta capa solo marca cost_known=True cuando el costo viene de una fuente configurada
como proveedor y contiene evidencia suficiente para usarlo en la economía de venta.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


class SupplierSourceError(RuntimeError):
    pass


@dataclass
class SupplierCandidate:
    name: str
    cost: float
    url: str = ""
    supplier_name: str = ""
    shipping_cost: float = 0.0
    available: bool = True
    verified: bool = False
    currency: str = "MXN"
    source: str = "configured_feed"
    source_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JsonSupplierSource:
    """Lee un catálogo local JSON/CSV proporcionado por el usuario/proveedor."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.getenv("AUTOBRILLO_SUPPLIER_FEED", "suppliers.json"))

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            if self.path.suffix.lower() == ".csv":
                with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
                    return list(csv.DictReader(fh))
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data = data.get("products", data.get("results", []))
            return data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError) as exc:
            raise SupplierSourceError(f"No se pudo leer el catálogo de proveedor: {exc}") from exc

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def search(self, query: str, limit: int = 20) -> List[SupplierCandidate]:
        terms = {x for x in query.casefold().split() if len(x) >= 3}
        rows = self._load()
        scored: List[tuple[int, Dict[str, Any]]] = []
        for row in rows:
            name = str(row.get("name", row.get("title", ""))).strip()
            haystack = name.casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        result: List[SupplierCandidate] = []
        for _, row in scored[: max(1, min(int(limit), 50))]:
            cost = self._float(row.get("cost", row.get("supplier_cost")))
            verified = bool(row.get("verified", True)) and cost > 0
            result.append(SupplierCandidate(
                name=str(row.get("name", row.get("title", ""))).strip(),
                cost=cost,
                url=str(row.get("url", row.get("link", ""))),
                supplier_name=str(row.get("supplier_name", row.get("supplier", ""))),
                shipping_cost=self._float(row.get("shipping_cost", row.get("shipping", 0))),
                available=bool(row.get("available", True)),
                verified=verified,
                currency=str(row.get("currency", "MXN")),
                source=str(row.get("source", "configured_feed")),
                source_id=str(row.get("source_id", row.get("id", ""))),
            ))
        return result


def search_suppliers(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Busca costos reales solo en la fuente de proveedor configurada."""
    source = os.getenv("AUTOBRILLO_SUPPLIER_SOURCE", "json").casefold()
    if source == "json":
        return [x.to_dict() for x in JsonSupplierSource().search(query, limit)]
    raise SupplierSourceError(f"Fuente de proveedor no soportada: {source}")
