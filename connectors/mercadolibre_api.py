from __future__ import annotations

import os
from typing import Any

import requests

from connectors.mercadolibre_oauth import MercadoLibreOAuth


class MercadoLibreAPI:
    """Cliente de Mercado Libre para catálogo y operaciones del seller."""

    BASE_URL = "https://api.mercadolibre.com"

    def __init__(self, oauth: MercadoLibreOAuth | None = None):
        self.oauth = oauth or MercadoLibreOAuth()
        self.timeout = float(os.getenv("ML_API_TIMEOUT", "20"))
        self.site = os.getenv("ML_SITE", "MLM").strip().upper() or "MLM"

    def _token(self) -> str:
        token = self.oauth.load_token()
        if not token or not token.get("access_token"):
            raise RuntimeError("Mercado Libre no está autorizado todavía.")
        return str(token["access_token"])

    @staticmethod
    def _decode_response(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:1000]}
        if not isinstance(data, dict):
            return {"data": data}
        return data

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._token()}"
        headers.setdefault("Accept", "application/json")
        response = requests.request(
            method,
            f"{self.BASE_URL}{path}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        data = self._decode_response(response)
        if not response.ok:
            detail = data.get("message") or data.get("error_description") or data.get("error")
            code = data.get("code") or data.get("error")
            suffix = f" ({code})" if code else ""
            raise RuntimeError(f"Mercado Libre API {response.status_code}: {detail or 'solicitud rechazada'}{suffix}")
        return data

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/users/me")

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Busca productos de catálogo usando el recurso soportado para consultas por texto.

        /sites/{site}/search ya no debe usarse como buscador genérico por q para
        este flujo: la documentación vigente dirige las búsquedas de catálogo a
        /products/search con site_id, status y q. Después enriquecemos cada
        producto con /products/{id} para obtener buy_box_winner, precio y enlace.
        """
        query = query.strip()
        if not query:
            raise ValueError("La búsqueda no puede estar vacía.")
        limit = max(1, min(int(limit), 20))
        data = self.request(
            "GET",
            "/products/search",
            params={"status": "active", "site_id": self.site, "q": query, "limit": limit},
        )

        results = []
        for item in data.get("results", [])[:limit]:
            product_id = str(item.get("id") or "").strip()
            if not product_id:
                continue
            try:
                detail = self.request("GET", f"/products/{product_id}")
            except RuntimeError:
                detail = item
            results.append(detail)
        data["results"] = results
        return data

    def item(self, item_id: str) -> dict[str, Any]:
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Falta el ID del producto.")
        return self.request("GET", f"/items/{item_id}")
