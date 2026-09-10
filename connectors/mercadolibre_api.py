from __future__ import annotations

import os
from typing import Any

import requests

from connectors.mercadolibre_oauth import MercadoLibreOAuth


class MercadoLibreAPI:
    BASE_URL = "https://api.mercadolibre.com"

    def __init__(self, oauth: MercadoLibreOAuth | None = None):
        self.oauth = oauth or MercadoLibreOAuth()
        self.timeout = float(os.getenv("ML_API_TIMEOUT", "20"))
        self.site = os.getenv("ML_SITE", "MLM").strip().upper() or "MLM"
        self.user_agent = os.getenv("ML_API_USER_AGENT", "AutoBrillo-AI/7.0")

    def _token(self) -> str:
        token = self.oauth.access_token()
        if not token:
            raise RuntimeError("Mercado Libre no está autorizado todavía.")
        return token

    @staticmethod
    def _decode_response(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:1000]}
        return data if isinstance(data, dict) else {"data": data}

    def request(self, method: str, path: str, *, authenticated: bool = True, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token()}"
        headers.setdefault("Accept", "application/json")
        headers.setdefault("User-Agent", self.user_agent)
        response = requests.request(method, f"{self.BASE_URL}{path}", headers=headers, timeout=self.timeout, **kwargs)
        data = self._decode_response(response)
        if not response.ok:
            detail = data.get("message") or data.get("error_description") or data.get("error") or "solicitud rechazada"
            code = data.get("code") or data.get("error") or ""
            if response.status_code == 403:
                raise RuntimeError(f"Mercado Libre 403 Forbidden: {detail} ({code or 'FORBIDDEN'}). Revisa scopes, estado de la app, usuario propietario y restricciones de Mercado Libre.")
            raise RuntimeError(f"Mercado Libre API {response.status_code}: {detail}{f' ({code})' if code else ''}")
        return data

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/users/me", authenticated=True)

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("La búsqueda no puede estar vacía.")
        limit = max(1, min(int(limit), 50))
        return self.request("GET", f"/sites/{self.site}/search", authenticated=True, params={"q": query, "limit": limit})

    def item(self, item_id: str) -> dict[str, Any]:
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Falta el ID del producto.")
        return self.request("GET", f"/items/{item_id}", authenticated=True)
