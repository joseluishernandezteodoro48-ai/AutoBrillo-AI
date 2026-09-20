# AutoBrillo AI - SalesAgent / Tygo core
import argparse
import html
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from model import AutoBrilloBrain
from persistence import Persistence

PERMISSIONS = (
    "web",
    "social",
    "sales",
    "payments",
    "marketing",
    "analytics",
    "products",
    "logistics",
)


class Memory:
    """Capa de memoria que usa Persistence (Postgres o SQLite)."""

    def __init__(self, db: str | None = None):
        self._p = Persistence(sqlite_path=db or os.environ.get("AUTOBRILLO_DB", "autobrillo.db"))
        self.db = self._p.sqlite_path  # compatibilidad con GoalAgent antiguo

    def remember(self, kind: str, data: Any, outcome: Optional[str] = None) -> None:
        self._p.remember(kind, data, outcome)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._p.recent(limit)

    def set_permission(self, name: str, enabled: bool = True) -> None:
        if name not in PERMISSIONS:
            raise ValueError("Permiso desconocido: " + name)
        self._p.set_permission(name, enabled)

    def allowed(self, name: str) -> bool:
        return self._p.allowed(name)

    def metric(self, product: str, event: str, value: float = 0) -> None:
        self._p.metric(product, event, value)

    def metrics(self, product: Optional[str] = None) -> dict[str, dict[str, float]]:
        return self._p.metrics(product)

    def backend(self) -> str:
        return self._p.backend()

    def health(self) -> dict[str, Any]:
        return self._p.health()


@dataclass
class Product:
    name: str
    price: float
    cost: float = 0
    commission: float = 0
    url: str = ""
    active: bool = True
    score: float = 0
    shipping_cost: float = 0
    fixed_fee: float = 0
    tax_rate: float = 0
    cost_known: bool = False

    @property
    def commission_value(self) -> float:
        return self.price * self.commission if 0 < self.commission < 1 else self.commission

    @property
    def tax_value(self) -> float:
        return self.price * max(0, self.tax_rate) if self.tax_rate < 1 else max(0, self.tax_rate)

    @property
    def total_cost(self) -> float:
        return (
            max(0, self.cost)
            + max(0, self.shipping_cost)
            + max(0, self.fixed_fee)
            + self.commission_value
            + self.tax_value
        )

    @property
    def estimated_profit(self) -> float:
        return self.price - self.total_cost

    @property
    def margin(self) -> float:
        return self.estimated_profit / max(self.price, 1)


@dataclass
class Order:
    order_id: str
    product: str
    buyer_id: str = ""
    supplier_id: str = ""
    buyer_address: dict | None = None
    supplier_address: dict | None = None
    status: str = "pending"
    tracking: str = ""


class LogisticsManager:
    """Gestiona el flujo comprador -> proveedor -> envío sin exponer datos de dirección en logs."""

    def __init__(self, memory: Memory):
        self.memory = memory

    def _safe_address(self, address: dict) -> dict:
        if not isinstance(address, dict):
            raise ValueError("La dirección debe ser un objeto")
        required = ("street", "city", "state", "postal_code", "country")
        missing = [x for x in required if not address.get(x)]
        if missing:
            raise ValueError("Faltan campos de dirección: " + ", ".join(missing))
        return {k: str(address[k]).strip() for k in required if address.get(k)}

    def validate(self, address: dict) -> dict:
        a = self._safe_address(address)
        return {"valid": True, "country": a["country"], "city": a["city"], "postal_code": a["postal_code"]}

    def register_order(self, order: Order) -> dict:
        if not self.memory.allowed("logistics"):
            raise PermissionError("Permiso logistics requerido")
        buyer = self._safe_address(order.buyer_address or {})
        supplier = self._safe_address(order.supplier_address or {})
        if not order.order_id:
            raise ValueError("order_id requerido")
        self.memory.remember(
            "order_created",
            {
                "order_id": order.order_id,
                "product": order.product,
                "buyer_id": order.buyer_id,
                "supplier_id": order.supplier_id,
                "status": order.status,
            },
            "created",
        )
        self.memory.remember(
            "address_validation",
            {
                "order_id": order.order_id,
                "buyer": self.validate(buyer),
                "supplier": self.validate(supplier),
            },
            "validated",
        )
        return {"ok": True, "order_id": order.order_id, "status": order.status}

    def prepare_fulfillment(self, order_id: str, product: str) -> dict:
        if not self.memory.allowed("logistics"):
            raise PermissionError("Permiso logistics requerido")
        self.memory.remember(
            "fulfillment_prepared", {"order_id": order_id, "product": product}, "prepared"
        )
        return {"ok": True, "order_id": order_id, "next": "supplier_dispatch"}

    def update_tracking(self, order_id: str, tracking: str, status: str = "shipped") -> dict:
        if not self.memory.allowed("logistics"):
            raise PermissionError("Permiso logistics requerido")
        if not tracking:
            raise ValueError("tracking requerido")
        self.memory.remember(
            "shipment_update",
            {"order_id": order_id, "tracking": tracking, "status": status},
            "updated",
        )
        return {"ok": True, "order_id": order_id, "tracking": tracking, "status": status}


class Catalog:
    """Catálogo persistente (Postgres o SQLite vía Persistence)."""

    def __init__(self, memory: Memory | None = None):
        self.memory = memory or Memory()
        self._p = self.memory._p
        self.products: list[Product] = []
        self.load()

    def load(self) -> None:
        self.products = []
        for x in self._p.load_catalog():
            x = dict(x)
            x.setdefault("shipping_cost", 0)
            x.setdefault("fixed_fee", 0)
            x.setdefault("tax_rate", 0)
            x.setdefault("cost_known", bool(x.get("cost", 0)))
            try:
                self.products.append(Product(**{k: v for k, v in x.items() if k in Product.__dataclass_fields__}))
            except TypeError:
                continue

    def save(self) -> None:
        for p in self.products:
            self._p.save_catalog_product(p.name, asdict(p))

    def add(self, p: Product) -> None:
        if any(x.name.lower() == p.name.lower() for x in self.products):
            raise ValueError("El producto ya existe")
        self.products.append(p)
        self._p.save_catalog_product(p.name, asdict(p))

    def update(self, p: Product) -> None:
        for i, existing in enumerate(self.products):
            if existing.name.lower() == p.name.lower():
                self.products[i] = p
                self._p.save_catalog_product(p.name, asdict(p))
                return
        self.add(p)

    def best(self, n: int = 10) -> list[Product]:
        return sorted(
            (p for p in self.products if p.active),
            key=lambda p: (p.score, p.estimated_profit),
            reverse=True,
        )[:n]


class SiteBuilder:
    def build(self, p: Product, folder: str = "sites") -> str:
        os.makedirs(folder, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", p.name.lower()).strip("-") or "producto"
        path = os.path.join(folder, slug + ".html")
        name, url = html.escape(p.name), html.escape(p.url, quote=True)
        doc = f"""<!doctype html><html lang="es-MX"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} | AutoBrillo</title></head><body>
<main><h1>{name}</h1><h2>${p.price:,.2f} MXN</h2>
<p>Oferta seleccionada por AutoBrillo AI.</p>
<a href="{url}" rel="nofollow sponsored" target="_blank">Ver producto</a>
</main></body></html>"""
        with open(path, "w", encoding="utf8") as f:
            f.write(doc)
        return path


class Connector:
    def __init__(self, name: str, permission: str, env_vars: tuple[str, ...]):
        self.name = name
        self.permission = permission
        self.env_vars = env_vars

    def configured(self) -> bool:
        return all(os.getenv(x) for x in self.env_vars)

    def status(self) -> dict:
        return {
            "name": self.name,
            "permission": self.permission,
            "configured": self.configured(),
        }


class SalesAgent:
    def __init__(self):
        self.memory = Memory()
        self.brain = AutoBrilloBrain()
        self.catalog = Catalog(self.memory)
        self.site_builder = SiteBuilder()
        self.logistics = LogisticsManager(self.memory)
        self.dry_run = os.getenv("AUTOBRILLO_DRY_RUN", "true").lower() != "false"
        self.kill = os.getenv("AUTOBRILLO_KILL_SWITCH", "false").lower() == "true"
        self.connectors = [
            Connector("Meta/Facebook", "social", ("META_ACCESS_TOKEN", "META_PAGE_ID")),
            Connector("Mercado Libre", "products", ("ML_CLIENT_ID", "ML_CLIENT_SECRET")),
            Connector("Analytics", "analytics", ("ANALYTICS_API_KEY",)),
            Connector("Logistics provider", "logistics", ("LOGISTICS_API_KEY",)),
        ]

    def learn(self, text: str, label: str):
        result = self.brain.add_examples([{"text": text, "label": label}])
        self.memory.remember("learning", {"text": text, "label": label}, "stored")
        return result

    def record_result(self, action: str, result: str, value: float = 0, product: Optional[str] = None):
        self.memory.remember(
            "sales_result", {"action": action, "value": value, "product": product}, result
        )
        self.memory.metric(product or "", action, value)

    def create_page(self, name: str) -> str:
        p = next((x for x in self.catalog.products if x.name == name), None)
        if not p:
            raise ValueError("Producto no encontrado")
        path = self.site_builder.build(p)
        self.memory.remember("page_created", {"product": p.name, "path": path}, "created")
        return path

    def score_products(self) -> None:
        for p in self.catalog.products:
            m = self.memory.metrics(p.name)
            clicks = m.get("click", {}).get("count", 0)
            sales = m.get("sale", {}).get("count", 0)
            rev = m.get("commission", {}).get("value", 0)
            conv = sales / clicks if clicks else 0
            margin = max(0, min(p.margin, 1)) if p.cost_known else 0
            data_quality = 1.0 if p.cost_known else 0.15
            p.score = round(
                0.45 * margin + 0.25 * min(conv, 1) + 0.15 * min(rev / 1000, 1) + 0.15 * data_quality,
                6,
            )
        self.catalog.save()
        self.memory.remember("scoring", {"products": len(self.catalog.products)}, "completed")

    def think(self) -> dict:
        candidates = []
        for p in self.catalog.products:
            m = self.memory.metrics(p.name)
            clicks = m.get("click", {}).get("count", 0)
            sales = m.get("sale", {}).get("count", 0)
            risk = 0.75 if not p.cost_known else 0.2
            candidates.append(
                {
                    "name": p.name,
                    "price": p.price,
                    "estimated_profit": p.estimated_profit if p.cost_known else 0,
                    "commission_value": p.commission_value,
                    "clicks": clicks,
                    "sales": sales,
                    "trend": min(1.0, max(0.0, p.score)),
                    "confidence": 0.8 if p.cost_known else 0.2,
                    "risk": risk,
                    "cost_known": p.cost_known,
                    "margin": p.margin if p.cost_known else None,
                }
            )
        decision = self.brain.think({"candidates": candidates})
        self.memory.remember("decision", decision, "computed")
        return decision

    def plan(self, limit: int = 5) -> list[dict]:
        self.score_products()
        decision = self.think()
        tasks = []
        ordered = [x.get("name") for x in decision.get("alternatives", []) if x.get("name")]
        for name in ordered[:limit]:
            item = next((p for p in self.catalog.products if p.name == name and p.active), None)
            if item:
                selected = next((x for x in decision["alternatives"] if x.get("name") == name), {})
                ready = item.cost_known and item.estimated_profit > 0
                tasks.append(
                    {
                        "action": "research_cost" if not item.cost_known else "prepare_sale",
                        "product": name,
                        "priority": selected.get("score", item.score),
                        "estimated_profit": round(item.estimated_profit, 2) if item.cost_known else None,
                        "margin": round(item.margin, 4) if item.cost_known else None,
                        "ready_to_sell": ready,
                        "reason": (
                            "falta costo real del proveedor"
                            if not item.cost_known
                            else ("margen positivo" if ready else "margen no rentable")
                        ),
                    }
                )
                if ready:
                    tasks.append(
                        {
                            "action": "create_page",
                            "product": name,
                            "priority": selected.get("score", item.score) * 0.95,
                            "estimated_profit": round(item.estimated_profit, 2),
                            "margin": round(item.margin, 4),
                        }
                    )
                    tasks.append(
                        {
                            "action": "prepare_listing",
                            "product": name,
                            "priority": selected.get("score", item.score) * 0.92,
                            "estimated_profit": round(item.estimated_profit, 2),
                            "margin": round(item.margin, 4),
                            "ready_to_sell": True,
                        }
                    )
                    if self.memory.allowed("sales"):
                        tasks.append(
                            {
                                "action": "publish",
                                "product": name,
                                "priority": selected.get("score", item.score) * 0.90,
                                "estimated_profit": round(item.estimated_profit, 2),
                                "margin": round(item.margin, 4),
                                "ready_to_sell": True,
                            }
                        )
        if self.memory.allowed("marketing"):
            for p in self.catalog.best(limit):
                if p.cost_known and p.estimated_profit > 0:
                    tasks.append(
                        {
                            "action": "prepare_marketing",
                            "product": p.name,
                            "priority": p.score * 0.9,
                        }
                    )
        return sorted(tasks, key=lambda x: x["priority"], reverse=True)

    def execute(self, task: dict, ml_api=None) -> dict:
        if self.kill:
            raise RuntimeError("KILL SWITCH activo")
        action = task["action"]
        if action == "create_page":
            return {"ok": True, "path": self.create_page(task["product"])}
        if action == "research_cost":
            self.memory.remember(
                "cost_research_needed", {"product": task["product"]}, "blocked_until_cost_known"
            )
            return {"ok": True, "product": task["product"], "status": "needs_supplier_cost"}
        if action == "prepare_sale":
            if not task.get("ready_to_sell"):
                return {"ok": False, "product": task["product"], "status": "not_profitable"}
            self.memory.remember("sale_prepared", {"product": task["product"]}, "ready_to_sell")
            return {
                "ok": True,
                "product": task["product"],
                "status": "ready_to_sell",
                "dry_run": self.dry_run,
            }
        if action == "prepare_marketing":
            self.memory.remember("marketing_draft", {"product": task["product"]}, "prepared")
            return {"ok": True, "draft": task["product"]}
        if action == "prepare_listing":
            return self.prepare_listing(task["product"], category_id=task.get("category_id"))
        if action == "publish":
            return self.publish_product(
                task["product"],
                ml_api=ml_api,
                category_id=task.get("category_id"),
                quantity=int(task.get("quantity") or 1),
            )
        if action in ("charge", "purchase", "transfer_money"):
            raise PermissionError(
                "Acción financiera requiere un conector oficial y permiso explícito"
            )
        raise ValueError("Acción desconocida")

    def prepare_listing(self, product_name: str, category_id: str | None = None) -> dict:
        """Arma el payload de publicación sin enviarlo a ML."""
        from connectors.mercadolibre_listing import product_to_payload

        p = next((x for x in self.catalog.products if x.name == product_name), None)
        if not p:
            raise ValueError("Producto no encontrado")
        if not p.cost_known or p.estimated_profit <= 0:
            return {
                "ok": False,
                "product": product_name,
                "status": "not_ready",
                "reason": "sin costo verificado o margen no positivo",
            }
        payload = product_to_payload(p, category_id=category_id)
        self.memory.remember(
            "listing_prepared",
            {"product": product_name, "title": payload.get("title"), "price": payload.get("price")},
            "prepared",
        )
        return {"ok": True, "product": product_name, "payload": payload, "dry_run": self.dry_run}

    def publish_product(
        self,
        product_name: str,
        *,
        ml_api=None,
        category_id: str | None = None,
        quantity: int = 1,
    ) -> dict:
        """Publica en Mercado Libre solo si dry_run=false y permiso sales activo."""
        if self.kill:
            raise RuntimeError("KILL SWITCH activo")
        if not self.memory.allowed("sales"):
            raise PermissionError("Permiso 'sales' requerido para publicar")
        if self.dry_run:
            prepared = self.prepare_listing(product_name, category_id=category_id)
            prepared["status"] = "dry_run_blocked"
            prepared["message"] = (
                "AUTOBRILLO_DRY_RUN=true: no se envió a Mercado Libre. "
                "Pon dry_run=false y permiso sales para publicar de verdad."
            )
            self.memory.remember(
                "publish_blocked_dry_run", {"product": product_name}, "blocked"
            )
            return prepared

        if ml_api is None:
            raise RuntimeError("Se requiere MercadoLibreAPI autenticada para publicar")

        prepared = self.prepare_listing(product_name, category_id=category_id)
        if not prepared.get("ok"):
            return prepared
        payload = prepared["payload"]
        payload["available_quantity"] = max(1, int(quantity))
        result = ml_api.publish_item(payload)
        item_id = result.get("id")
        self.memory.remember(
            "published",
            {"product": product_name, "item_id": item_id, "permalink": result.get("permalink")},
            "published",
        )
        self.record_result("publish", "published", value=float(payload.get("price") or 0), product=product_name)
        return {
            "ok": True,
            "product": product_name,
            "item_id": item_id,
            "permalink": result.get("permalink"),
            "status": "published",
            "raw": {"id": item_id, "status": result.get("status")},
        }

    def run_cycle(self, limit: int = 5, ml_api=None) -> dict:
        if self.kill:
            return {"stopped": True, "reason": "kill_switch"}
        tasks = self.plan(limit)
        results = []
        for t in tasks:
            try:
                results.append({"task": t, "result": self.execute(t, ml_api=ml_api)})
            except Exception as e:
                results.append({"task": t, "error": str(e)})
        self.memory.remember(
            "cycle", {"tasks": len(tasks), "dry_run": self.dry_run}, "completed"
        )
        return {"dry_run": self.dry_run, "tasks": results}

    def status(self) -> dict:
        return {
            "version": "v7.3",
            "products": len(self.catalog.products),
            "events": len(self.memory.recent(100000)),
            "brain_ready": self.brain.ready,
            "brain_stats": self.brain.stats(),
            "permissions": {k: self.memory.allowed(k) for k in PERMISSIONS},
            "dry_run": self.dry_run,
            "kill_switch": self.kill,
            "connectors": [c.status() for c in self.connectors],
            "planned_tasks": len(self.plan()),
            "persistence": self.memory.health(),
        }


def main():
    p = argparse.ArgumentParser(description="AutoBrillo AI v7.3")
    s = p.add_subparsers(dest="cmd")
    s.add_parser("status")
    s.add_parser("plan")
    s.add_parser("cycle")
    s.add_parser("connectors")
    s.add_parser("think")
    l = s.add_parser("learn")
    l.add_argument("text")
    l.add_argument("label")
    a = s.add_parser("add-product")
    a.add_argument("name")
    a.add_argument("price", type=float)
    a.add_argument("--cost", type=float, default=0)
    a.add_argument("--commission", type=float, default=0)
    a.add_argument("--shipping", type=float, default=0)
    a.add_argument("--fixed-fee", type=float, default=0)
    a.add_argument("--tax-rate", type=float, default=0)
    a.add_argument("--url", default="")
    perm = s.add_parser("permission")
    perm.add_argument("name", choices=PERMISSIONS)
    perm.add_argument("enabled", type=int, choices=(0, 1))
    args = p.parse_args()
    agent = SalesAgent()
    if args.cmd == "learn":
        agent.learn(args.text, args.label)
        print("Aprendizaje guardado")
    elif args.cmd == "add-product":
        agent.catalog.add(
            Product(
                args.name,
                args.price,
                args.cost,
                args.commission,
                args.url,
                shipping_cost=args.shipping,
                fixed_fee=args.fixed_fee,
                tax_rate=args.tax_rate,
                cost_known=True,
            )
        )
        print("Producto agregado")
    elif args.cmd == "plan":
        print(json.dumps(agent.plan(), ensure_ascii=False, indent=2))
    elif args.cmd == "think":
        print(json.dumps(agent.think(), ensure_ascii=False, indent=2))
    elif args.cmd == "cycle":
        print(json.dumps(agent.run_cycle(), ensure_ascii=False, indent=2))
    elif args.cmd == "connectors":
        print(json.dumps([c.status() for c in agent.connectors], ensure_ascii=False, indent=2))
    elif args.cmd == "permission":
        agent.memory.set_permission(args.name, bool(args.enabled))
        print("Permiso actualizado")
    else:
        print(json.dumps(agent.status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
