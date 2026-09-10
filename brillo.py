"""Brillo v6.1: interfaz de órdenes y orquestación de AutoBrillo AI."""
from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict

from autobrillo import Product, SalesAgent
from product_sources import ProductSourceError, search_products
from supplier_sources import SupplierSourceError, search_suppliers
from sourcing import compare_product_with_suppliers


class Brillo:
    """La cara del sistema: entiende la orden y coordina a Tygo/SalesAgent."""

    PRODUCT_COUNT = re.compile(r"\b(\d+)\b")

    def __init__(self, agent: SalesAgent | None = None):
        self.agent = agent or SalesAgent()

    def understand(self, command: str) -> Dict[str, Any]:
        text = str(command).strip()
        normalized = text.casefold()
        count_match = self.PRODUCT_COUNT.search(normalized)
        count = int(count_match.group(1)) if count_match else 5
        wants_sell = any(x in normalized for x in ("vender", "venta", "vende", "sell"))
        wants_find = any(x in normalized for x in ("consigue", "buscar", "busca", "encontrar", "productos"))
        wants_publish = any(x in normalized for x in ("publica", "publicar", "anuncia", "publicación"))
        intent = "source_and_sell" if wants_find and wants_sell else "sell" if wants_sell else "source" if wants_find else "general"
        return {"raw": text, "intent": intent, "product_count": max(1, min(count, 50)), "publish_requested": wants_publish}

    def source(self, query: str, count: int = 5) -> Dict[str, Any]:
        """Busca candidatos de venta y los incorpora al catálogo sin inventar costos."""
        candidates = search_products(query, count)
        added, skipped = [], []
        for item in candidates:
            try:
                self.agent.catalog.add(Product(
                    name=item["name"], price=float(item["price"]), cost=float(item.get("cost", 0)),
                    commission=float(item.get("commission", 0)), url=item.get("url", ""),
                    active=bool(item.get("active", True)), score=float(item.get("score", 0)),
                    shipping_cost=float(item.get("shipping_cost", 0)),
                    fixed_fee=float(item.get("fixed_fee", 0)), tax_rate=float(item.get("tax_rate", 0)),
                    cost_known=bool(item.get("cost_known", False)),
                ))
                added.append(item["name"])
            except ValueError:
                skipped.append(item["name"])
        self.agent.memory.remember("product_source", {"query": query, "found": len(candidates), "added": len(added)}, "completed")
        return {"found": len(candidates), "added": added, "skipped": skipped, "source": "mercadolibre", "cost_policy": "no asumir precio de venta como costo del proveedor"}

    def compare_suppliers(self, query: str, count: int = 5) -> Dict[str, Any]:
        """Busca proveedores configurados y compara sus costos con candidatos del marketplace."""
        products = search_products(query, count)
        suppliers = search_suppliers(query, max(count * 3, 10))
        comparisons = []
        for product in products:
            comparisons.extend(compare_product_with_suppliers(product, suppliers))
        comparisons.sort(key=lambda x: (x["cost_known"], x["projected_margin"], x["match_score"]), reverse=True)
        return {
            "products_found": len(products),
            "suppliers_found": len(suppliers),
            "comparisons": comparisons[: max(1, count * 3)],
            "ready": [x for x in comparisons if x["cost_known"] and x["projected_profit"] > 0][:count],
            "needs_verification": [x for x in comparisons if not x["cost_known"]][:count],
        }

    def respond(self, command: str) -> Dict[str, Any]:
        intent = self.understand(command)
        if intent["intent"] in ("source_and_sell", "source"):
            query = re.sub(r"\b\d+\b", "", intent["raw"], count=1).strip()
            query = re.sub(r"\b(consigue|busca|buscar|encontrar|productos|y|vende|vender|venta)\b", " ", query, flags=re.I).strip() or "productos populares"
            try:
                source_result = self.source(query, intent["product_count"])
                supplier_result = self.compare_suppliers(query, intent["product_count"])
            except (ProductSourceError, SupplierSourceError) as exc:
                return {"ok": False, "assistant": "Brillo", "brain": "Tygo/SalesAgent", "intent": intent, "error": str(exc)}
            plan = self.agent.plan(intent["product_count"])
            ready = [x["product"] for x in plan if x.get("ready_to_sell")]
            research = [x["product"] for x in plan if x.get("action") == "research_cost"]
            return {"ok": True, "assistant": "Brillo", "brain": "Tygo/SalesAgent", "intent": intent,
                    "source": source_result, "supplier_comparison": supplier_result, "status": "planned", "plan": plan,
                    "summary": {"ready_to_sell": ready, "needs_supplier_cost": research},
                    "next": "usar solo costos de proveedor verificados; después preparar publicación/venta con conectores oficiales"}

        if intent["intent"] == "sell":
            plan = self.agent.plan(intent["product_count"])
            return {"ok": True, "assistant": "Brillo", "brain": "Tygo/SalesAgent", "intent": intent,
                    "status": "planned", "plan": plan,
                    "next": "conectar canal de venta oficial", "financial_actions": "requieren autorización/conector oficial"}

        return {"ok": True, "assistant": "Brillo", "intent": intent,
                "status": "understood", "available": ["think", "plan", "learn", "source", "compare_suppliers", "sell"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Brillo v6.1 - interfaz de AutoBrillo AI")
    parser.add_argument("command", nargs="+", help="Orden para Brillo")
    args = parser.parse_args()
    print(json.dumps(Brillo().respond(" ".join(args.command)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
