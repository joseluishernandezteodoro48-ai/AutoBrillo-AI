"""Capa de autonomía de AutoBrillo.

Convierte instrucciones humanas en objetivos persistentes y planes verificables.
No ejecuta compras, cobros ni publicaciones por sí sola: esas acciones quedan
bloqueadas hasta que exista un conector oficial y el permiso correspondiente.
"""
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Goal:
    id: int
    text: str
    target_count: int
    action: str
    status: str
    created_at: float


class GoalAgent:
    def __init__(self, memory):
        self.memory = memory
        self.db = memory.db
        with sqlite3.connect(self.db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS goals(" 
                "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
                "target_count INTEGER NOT NULL, action TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS goal_tasks(" 
                "id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER NOT NULL, "
                "seq INTEGER NOT NULL, action TEXT NOT NULL, product TEXT, "
                "status TEXT NOT NULL, result TEXT, created_at REAL NOT NULL)"
            )

    @staticmethod
    def parse(text: str) -> tuple[int, str]:
        value = text.strip()
        if not value:
            raise ValueError("El objetivo no puede estar vacío")
        match = re.search(r"\b(\d{1,3})\b", value)
        count = int(match.group(1)) if match else 1
        if not 1 <= count <= 100:
            raise ValueError("La cantidad debe estar entre 1 y 100")
        lower = value.lower()
        if any(word in lower for word in ("vende", "vender", "venta", "vendelos", "véndelos")):
            action = "sell"
        elif any(word in lower for word in ("busca", "consigue", "encontra", "encuentra")):
            action = "source"
        else:
            action = "research"
        return count, action

    def create(self, text: str) -> Goal:
        count, action = self.parse(text)
        now = time.time()
        with sqlite3.connect(self.db) as c:
            cur = c.execute(
                "INSERT INTO goals(text,target_count,action,status,created_at) VALUES(?,?,?,?,?)",
                (text.strip(), count, action, "active", now),
            )
            goal_id = cur.lastrowid
        goal = Goal(goal_id, text.strip(), count, action, "active", now)
        self.memory.remember("goal_created", {"goal_id": goal.id, "action": action, "target_count": count}, "active")
        return goal

    def plan(self, goal: Goal) -> list[dict[str, Any]]:
        tasks = [
            {"action": "research_products", "count": goal.target_count, "status": "ready"},
            {"action": "evaluate_products", "count": goal.target_count, "status": "blocked_until_research"},
            {"action": "select_products", "count": goal.target_count, "status": "blocked_until_evaluation"},
        ]
        if goal.action == "sell":
            tasks.extend([
                {"action": "prepare_listings", "count": goal.target_count, "status": "blocked_until_selection"},
                {"action": "prepare_sales", "count": goal.target_count, "status": "blocked_until_selection"},
                {"action": "publish_listings", "count": goal.target_count, "status": "requires_official_channel_and_permission"},
                {"action": "fulfill_orders", "count": goal.target_count, "status": "requires_order_and_logistics_connector"},
                {"action": "measure_results", "count": goal.target_count, "status": "blocked_until_sales"},
                {"action": "learn_from_results", "count": goal.target_count, "status": "blocked_until_measurement"},
            ])
        else:
            tasks.extend([
                {"action": "report_findings", "count": goal.target_count, "status": "blocked_until_selection"},
                {"action": "learn_from_results", "count": goal.target_count, "status": "blocked_until_measurement"},
            ])
        with sqlite3.connect(self.db) as c:
            c.execute("DELETE FROM goal_tasks WHERE goal_id=?", (goal.id,))
            for seq, task in enumerate(tasks, 1):
                c.execute(
                    "INSERT INTO goal_tasks(goal_id,seq,action,product,status,result,created_at) VALUES(?,?,?,?,?,?,?)",
                    (goal.id, seq, task["action"], None, task["status"], json.dumps(task, ensure_ascii=False), time.time()),
                )
        self.memory.remember("goal_planned", {"goal_id": goal.id, "tasks": len(tasks)}, "planned")
        return tasks

    def list_active(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db) as c:
            rows = c.execute(
                "SELECT id,text,target_count,action,status,created_at FROM goals WHERE status='active' ORDER BY id DESC"
            ).fetchall()
        return [asdict(Goal(*row)) for row in rows]

    def execute_safe(self, goal: Goal, sales_agent, limit: int = 5) -> dict[str, Any]:
        """Run only reversible/local preparation steps.

        External publication, purchasing, charging and money transfers are never
        performed here. The method instead reports the exact missing capability.
        """
        if sales_agent.kill:
            return {"stopped": True, "reason": "kill_switch"}
        plan = self.plan(goal)
        local = []
        for task in plan:
            if task["action"] == "research_products":
                local.append({"action": task["action"], "status": "needs_research_connector", "count": min(limit, goal.target_count)})
            elif task["action"] == "evaluate_products":
                local.append({"action": task["action"], "status": "ready_if_products_exist"})
            elif task["action"] in {"prepare_listings", "prepare_sales"}:
                local.append({"action": task["action"], "status": "safe_preparation_only"})
            elif task["action"] in {"publish_listings", "fulfill_orders"}:
                local.append({"action": task["action"], "status": task["status"]})
        return {"goal": asdict(goal), "plan": local, "dry_run": sales_agent.dry_run}
