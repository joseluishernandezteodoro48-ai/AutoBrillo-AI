"""Emparejamiento marketplace-proveedor y economía de abastecimiento."""
from __future__ import annotations

import re
from typing import Any, Dict, List


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9áéíóúñ]+", str(text).casefold()) if len(x) >= 3}


def match_score(product_name: str, supplier_name: str) -> float:
    a, b = _tokens(product_name), _tokens(supplier_name)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare_product_with_suppliers(product: Dict[str, Any], suppliers: List[Dict[str, Any]], commission_rate: float = 0.0, tax_rate: float = 0.0, fixed_fee: float = 0.0) -> List[Dict[str, Any]]:
    """Calcula opciones sin inventar costos. Solo proveedores verificados entran como costo utilizable."""
    price = float(product.get("price") or 0)
    results: List[Dict[str, Any]] = []
    for supplier in suppliers:
        cost = float(supplier.get("cost") or 0)
        shipping = float(supplier.get("shipping_cost") or 0)
        verified = bool(supplier.get("verified")) and cost > 0 and bool(supplier.get("available", True))
        total = cost + shipping + fixed_fee + (price * commission_rate) + (price * tax_rate) if verified else 0.0
        profit = price - total if verified else 0.0
        margin = profit / price if verified and price > 0 else 0.0
        results.append({
            "product": product.get("name", ""),
            "supplier": supplier.get("supplier_name") or supplier.get("name", ""),
            "supplier_product": supplier.get("name", ""),
            "supplier_cost": cost if verified else None,
            "shipping_cost": shipping if verified else None,
            "cost_known": verified,
            "match_score": round(match_score(str(product.get("name", "")), str(supplier.get("name", ""))), 4),
            "projected_profit": round(profit, 2),
            "projected_margin": round(margin, 4),
            "supplier_url": supplier.get("url", ""),
            "verified": verified,
            "reason": "costo verificado" if verified else "costo no verificado: no usar para decidir una venta",
        })
    return sorted(results, key=lambda x: (x["cost_known"], x["match_score"], x["projected_margin"]), reverse=True)
