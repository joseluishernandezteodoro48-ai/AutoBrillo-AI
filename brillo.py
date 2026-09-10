"""Brillo: interfaz de órdenes para AutoBrillo AI.

Brillo es la cara del sistema: recibe una orden en lenguaje natural y la
convierte en una intención estructurada que Tygo/SalesAgent puede planificar.
No ejecuta pagos, compras ni publicaciones irreversibles por sí mismo.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict

from autobrillo import SalesAgent


class Brillo:
    """Capa de entrada y orquestación segura sobre SalesAgent."""

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

        if wants_find and wants_sell:
            intent = "source_and_sell"
        elif wants_sell:
            intent = "sell"
        elif wants_find:
            intent = "source"
        else:
            intent = "general"

        return {
            "raw": text,
            "intent": intent,
            "product_count": max(1, min(count, 50)),
            "publish_requested": wants_publish,
        }

    def respond(self, command: str) -> Dict[str, Any]:
        intent = self.understand(command)

        # Tygo recibe candidatos del catálogo actual. La búsqueda externa se
        # deja como etapa de conector, nunca se simula como si hubiera ocurrido.
        if intent["intent"] in ("source_and_sell", "sell"):
            plan = self.agent.plan(intent["product_count"])
            return {
                "ok": True,
                "assistant": "Brillo",
                "brain": "Tygo/SalesAgent",
                "intent": intent,
                "status": "planned",
                "plan": plan,
                "next": "conectar fuente de productos y canal de venta oficial",
                "financial_actions": "requieren autorización/conector oficial",
            }

        if intent["intent"] == "source":
            return {
                "ok": True,
                "assistant": "Brillo",
                "intent": intent,
                "status": "ready",
                "next": "ejecutar búsqueda mediante un conector de productos autorizado",
            }

        return {
            "ok": True,
            "assistant": "Brillo",
            "intent": intent,
            "status": "understood",
            "available": ["think", "plan", "learn", "source", "sell"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Brillo - interfaz de AutoBrillo AI")
    parser.add_argument("command", nargs="+", help="Orden para Brillo")
    args = parser.parse_args()
    result = Brillo().respond(" ".join(args.command))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
