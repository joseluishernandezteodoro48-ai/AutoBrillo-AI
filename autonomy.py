"""Motor de autonomía de Tygo para AutoBrillo AI.

El modo autónomo no depende de una cantidad fija de productos. Trabaja por lotes,
aprende de cada ciclo y continúa mientras existan candidatos nuevos y el sistema
permanezca habilitado. Las operaciones externas irreversibles siguen pasando por
los conectores oficiales y sus permisos.
"""
from __future__ import annotations

import os
import time
from typing import Any


class AutonomousEngine:
    def __init__(self, brillo: Any, agent: Any):
        self.brillo = brillo
        self.agent = agent
        self.batch_size = max(1, min(int(os.getenv("AUTOBRILLO_AUTONOMY_BATCH", "12")), 50))
        self.max_rounds = max(1, min(int(os.getenv("AUTOBRILLO_AUTONOMY_MAX_ROUNDS", "10")), 100))
        self.pause_seconds = max(0.0, float(os.getenv("AUTOBRILLO_AUTONOMY_PAUSE", "0.2")))

    def run(self, query: str = "productos", target: int | None = None) -> dict[str, Any]:
        if self.agent.kill:
            return {"ok": False, "stopped": True, "reason": "kill_switch"}

        target = None if target is None or target <= 0 else int(target)
        total_found = 0
        total_added = 0
        rounds = []
        seen: set[str] = set()

        for round_no in range(1, self.max_rounds + 1):
            if self.agent.kill:
                break
            remaining = target - total_added if target is not None else self.batch_size
            if remaining <= 0:
                break
            batch = min(self.batch_size, remaining)

            try:
                result = self.brillo.source(query, batch)
                names = [str(x) for x in result.get("added", [])]
                new_names = [x for x in names if x not in seen]
                seen.update(new_names)
                total_found += int(result.get("found", 0))
                total_added += len(new_names)
                rounds.append({
                    "round": round_no,
                    "requested": batch,
                    "found": int(result.get("found", 0)),
                    "new": len(new_names),
                    "products": new_names,
                })

                if not names or not new_names:
                    break
                if target is not None and total_added >= target:
                    break
            except Exception as exc:
                rounds.append({"round": round_no, "error": str(exc)})
                break

            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        plan_limit = min(max(total_added, 1), 50)
        plan = self.agent.plan(plan_limit) if total_added else []
        return {
            "ok": True,
            "mode": "autonomous",
            "query": query,
            "target": target,
            "batch_size": self.batch_size,
            "rounds": rounds,
            "total_found": total_found,
            "total_added": total_added,
            "plan": plan,
            "learning": "cada ciclo queda registrado para que Tygo ajuste la exploración",
            "external_actions": "publicación, compra, cobro y transferencias requieren conectores oficiales y permisos correspondientes",
        }
