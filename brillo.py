"""Brillo v7.3: interfaz de órdenes y orquestación de AutoBrillo AI."""
from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict

from autobrillo import Product, SalesAgent
from product_sources import ProductSourceError, search_products
from supplier_sources import SupplierSourceError, search_suppliers
from sourcing import compare_product_with_suppliers
from tygo_search import TygoSearchDecision


class Brillo:
    """La cara del sistema: entiende la orden y coordina a Tygo/SalesAgent."""

    PRODUCT_COUNT = re.compile(r"\b(\d+)\b")

    def __init__(self, agent: SalesAgent | None = None):
        self.agent = agent or SalesAgent()
        self.tygo_search = TygoSearchDecision()

    def understand(self, command: str) -> Dict[str, Any]:
        text = str(command).strip()
        normalized = text.casefold()
        count_match = self.PRODUCT_COUNT.search(normalized)
        explicit_count = int(count_match.group(1)) if count_match else None
        wants_sell = any(x in normalized for x in ("vender", "venta", "vende", "sell"))
        wants_find = any(
            x in normalized for x in ("consigue", "buscar", "busca", "encontrar", "productos")
        )
        wants_publish = any(
            x in normalized for x in ("publica", "publicar", "anuncia", "publicación")
        )
        intent = (
            "source_and_sell"
            if wants_find and wants_sell
            else "sell"
            if wants_sell
            else "source"
            if wants_find
            else "general"
        )

        if explicit_count is not None:
            product_count = max(1, min(explicit_count, 50))
            count_source = "user"
            count_reason = "cantidad indicada explícitamente por el usuario"
        elif wants_find:
            decision = self.tygo_search.choose_count(self.agent, text)
            product_count = decision["count"]
            count_source = "tygo"
            count_reason = decision["reason"]
        else:
            product_count = None
            count_source = "not_applicable"
            count_reason = "la orden no requiere sourcing"

        return {
            "raw": text,
            "intent": intent,
            "product_count": product_count,
            "product_count_source": count_source,
            "product_count_reason": count_reason,
            "publish_requested": wants_publish,
        }

    def _apply_best_supplier_cost(
        self, product_name: str, price: float, comparisons: list[dict]
    ) -> dict[str, Any]:
        """Elige el mejor proveedor verificado y devuelve costo/shipping/cost_known."""
        ready = [
            c
            for c in comparisons
            if c.get("cost_known")
            and c.get("verified")
            and (c.get("projected_profit") or 0) > 0
            and c.get("product", "").lower() == product_name.lower()
        ]
        if not ready:
            # fallback: cualquier costo verificado del mismo producto
            ready = [
                c
                for c in comparisons
                if c.get("cost_known") and c.get("verified") and c.get("product", "").lower() == product_name.lower()
            ]
        if not ready:
            return {
                "cost": 0.0,
                "shipping_cost": 0.0,
                "cost_known": False,
                "supplier": None,
                "projected_margin": None,
            }
        best = ready[0]
        return {
            "cost": float(best.get("supplier_cost") or 0),
            "shipping_cost": float(best.get("shipping_cost") or 0),
            "cost_known": True,
            "supplier": best.get("supplier"),
            "projected_margin": best.get("projected_margin"),
        }

    def source(self, query: str, count: int) -> Dict[str, Any]:
        """Busca candidatos de venta, compara con proveedores y solo marca cost_known cuando hay evidencia."""
        if count < 1:
            raise ValueError("count debe ser mayor que cero")
        candidates = search_products(query, count)
        try:
            suppliers = search_suppliers(query, max(count * 3, 10))
        except SupplierSourceError:
            suppliers = []

        comparisons: list[dict] = []
        for product in candidates:
            comparisons.extend(compare_product_with_suppliers(product, suppliers))
        comparisons.sort(
            key=lambda x: (x["cost_known"], x["projected_margin"], x["match_score"]),
            reverse=True,
        )

        added, skipped, enriched = [], [], []
        for item in candidates:
            cost_info = self._apply_best_supplier_cost(
                item["name"], float(item["price"]), comparisons
            )
            try:
                product = Product(
                    name=item["name"],
                    price=float(item["price"]),
                    cost=cost_info["cost"],
                    commission=float(item.get("commission", 0.13)),  # comisión típica ML ~13%
                    url=item.get("url", ""),
                    active=bool(item.get("active", True)),
                    score=float(item.get("score", 0)),
                    shipping_cost=cost_info["shipping_cost"],
                    fixed_fee=float(item.get("fixed_fee", 0)),
                    tax_rate=float(item.get("tax_rate", 0)),
                    cost_known=cost_info["cost_known"],
                )
                self.agent.catalog.add(product)
                added.append(item["name"])
                enriched.append(
                    {
                        "name": item["name"],
                        "price": product.price,
                        "cost_known": product.cost_known,
                        "cost": product.cost if product.cost_known else None,
                        "shipping_cost": product.shipping_cost if product.cost_known else None,
                        "estimated_profit": round(product.estimated_profit, 2)
                        if product.cost_known
                        else None,
                        "margin": round(product.margin, 4) if product.cost_known else None,
                        "supplier": cost_info["supplier"],
                    }
                )
            except ValueError:
                skipped.append(item["name"])

        self.agent.memory.remember(
            "product_source",
            {
                "query": query,
                "found": len(candidates),
                "added": len(added),
                "count": count,
                "suppliers_found": len(suppliers),
                "with_known_cost": sum(1 for e in enriched if e["cost_known"]),
            },
            "completed",
        )
        return {
            "found": len(candidates),
            "added": added,
            "skipped": skipped,
            "requested": count,
            "source": "mercadolibre",
            "suppliers_found": len(suppliers),
            "enriched": enriched,
            "cost_policy": "solo se marca cost_known cuando existe proveedor verificado con costo > 0",
        }

    def compare_suppliers(self, query: str, count: int) -> Dict[str, Any]:
        """Busca proveedores configurados y compara sus costos con candidatos del marketplace."""
        products = search_products(query, count)
        suppliers = search_suppliers(query, max(count * 3, 10))
        comparisons = []
        for product in products:
            comparisons.extend(compare_product_with_suppliers(product, suppliers))
        comparisons.sort(
            key=lambda x: (x["cost_known"], x["projected_margin"], x["match_score"]),
            reverse=True,
        )
        return {
            "products_found": len(products),
            "suppliers_found": len(suppliers),
            "requested": count,
            "comparisons": comparisons[: max(1, count * 3)],
            "ready": [x for x in comparisons if x["cost_known"] and x["projected_profit"] > 0][:count],
            "needs_verification": [x for x in comparisons if not x["cost_known"]][:count],
        }

    def respond(self, command: str) -> Dict[str, Any]:
        intent = self.understand(command)
        if intent["intent"] in ("source_and_sell", "source"):
            query = re.sub(r"\b\d+\b", "", intent["raw"], count=1).strip()
            query = re.sub(
                r"\b(consigue|busca|buscar|encontrar|productos|y|vende|vender|venta)\b",
                " ",
                query,
                flags=re.I,
            ).strip() or "productos populares"
            count = int(intent["product_count"])
            try:
                source_result = self.source(query, count)
                supplier_result = self.compare_suppliers(query, count)
            except (ProductSourceError, SupplierSourceError) as exc:
                return {
                    "ok": False,
                    "assistant": "Brillo",
                    "brain": "Tygo/SalesAgent",
                    "intent": intent,
                    "error": str(exc),
                }
            plan = self.agent.plan(count)
            ready = [x["product"] for x in plan if x.get("ready_to_sell")]
            research = [x["product"] for x in plan if x.get("action") == "research_cost"]
            return {
                "ok": True,
                "assistant": "Brillo",
                "brain": "Tygo/SalesAgent",
                "intent": intent,
                "source": source_result,
                "supplier_comparison": supplier_result,
                "status": "planned",
                "plan": plan,
                "summary": {"ready_to_sell": ready, "needs_supplier_cost": research},
                "next": (
                    "usar solo costos de proveedor verificados; "
                    "después preparar publicación/venta con conectores oficiales"
                ),
            }

        if intent["intent"] == "sell":
            plan = self.agent.plan(int(intent["product_count"] or 10))
            return {
                "ok": True,
                "assistant": "Brillo",
                "brain": "Tygo/SalesAgent",
                "intent": intent,
                "status": "planned",
                "plan": plan,
                "next": "conectar canal de venta oficial",
                "financial_actions": "requieren autorización/conector oficial",
            }

        return {
            "ok": True,
            "assistant": "Brillo",
            "intent": intent,
            "status": "understood",
            "available": ["think", "plan", "learn", "source", "compare_suppliers", "sell"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Brillo v7.3 - interfaz de AutoBrillo AI")
    parser.add_argument("command", nargs="+", help="Orden para Brillo")
    args = parser.parse_args()
    print(json.dumps(Brillo().respond(" ".join(args.command)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
