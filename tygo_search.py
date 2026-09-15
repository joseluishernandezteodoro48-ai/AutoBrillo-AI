"""Decisión de exploración de Tygo/SalesAgent para sourcing.

El número de candidatos no se fija en Brillo. Tygo lo decide con señales
observables del catálogo y del historial, manteniendo un límite de seguridad.
"""
from __future__ import annotations

from typing import Any, Dict


class TygoSearchDecision:
    MIN_RESULTS = 6
    MAX_RESULTS = 30

    def choose_count(self, agent: Any, query: str = "") -> Dict[str, Any]:
        catalog_size = len(getattr(agent.catalog, "products", []))
        try:
            events = agent.memory.recent(100)
        except Exception:
            events = []

        source_events = sum(1 for e in events if e.get("kind") == "product_source")
        sales_events = sum(1 for e in events if e.get("kind") == "sales_result" and e.get("outcome") in ("sale", "sold", "completed"))
        learning_events = sum(1 for e in events if e.get("kind") == "learning")

        # Exploración amplia cuando hay poca evidencia; reducción gradual cuando
        # ya existen señales de ventas/aprendizaje. Esto es una política
        # determinista y auditable, no una afirmación de ML autónomo.
        count = 12
        reasons = ["hay poca evidencia histórica; Tygo prioriza exploración"]
        if catalog_size == 0:
            count += 4
            reasons.append("catálogo vacío: aumenta la exploración inicial")
        elif catalog_size >= 20:
            count -= 3
            reasons.append("catálogo amplio: concentra la búsqueda")
        if source_events >= 5:
            count -= 2
            reasons.append("ya existen varias rondas de sourcing")
        if sales_events >= 3:
            count -= 2
            reasons.append("hay señales de ventas: aumenta la explotación")
        if learning_events >= 5:
            count += 1
            reasons.append("hay aprendizaje acumulado: permite explorar una alternativa más")

        count = max(self.MIN_RESULTS, min(self.MAX_RESULTS, count))
        return {
            "count": count,
            "source": "tygo",
            "reason": "; ".join(reasons),
            "signals": {
                "catalog_size": catalog_size,
                "recent_source_rounds": source_events,
                "recent_sales": sales_events,
                "recent_learning": learning_events,
                "query": query,
            },
            "policy": "exploracion_adaptativa_con_limite_de_seguridad",
        }
