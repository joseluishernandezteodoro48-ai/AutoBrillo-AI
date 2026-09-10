from __future__ import annotations

import os
from typing import Any

import requests

from connectors.mercadolibre_oauth import MercadoLibreOAuth


class MercadoLibreAPI:
    """Small authenticated client for Mercado Libre Mexico APIs.

    Tokens are read through the existing OAuth connector; secrets are never
    returned by this class.
    """

    BASE_URL = "https://api.mercadolibre.com"

    def __init__(self, oauth: MercadoLibreOAuth | None = None):
        self.oauth = oauth or MercadoLibreOAuth()
        self.timeout = float(os.getenv("ML_API_TIMEOUT", "20"))

    def _token(self) -> str:
        token = self.oauth.load_token()
        if not token or not token.get("access_token"):
            raise RuntimeError("Mercado Libre no está autorizado todavía.")
        return str(token["access_token"])

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
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:1000]}
        if not response.ok:
            detail = data.get("message") if isinstance(data, dict) else None
            raise RuntimeError(f"Mercado Libre API {response.status_code}: {detail or 'solicitud rechazada'}")
        return data if isinstance(data, dict) else {"data": data}

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/users/me")

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("La búsqueda no puede estar vacía.")
        limit = max(1, min(int(limit), 50))
        return self.request("GET", "/sites/MLM/search", params={"q": query, "limit": limit})

    def item(self, item_id: str) -> dict[str, Any]:
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Falta el ID del producto.")
        return self.request("GET", f"/items/{item_id}")
