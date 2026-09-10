from __future__ import annotations

import os
from typing import Any

import requests

from connectors.mercadolibre_oauth import MercadoLibreOAuth


class MercadoLibreAPI:
    """Cliente de Mercado Libre.

    La búsqueda de publicaciones puede funcionar con el access token o como
    consulta pública. Las operaciones de cuenta/vendedor siguen usando token.
    """

    BASE_URL = "https://api.mercadolibre.com"

    def __init__(self, oauth: MercadoLibreOAuth | None = None):
        self.oauth = oauth or MercadoLibreOAuth()
        self.timeout = float(os.getenv("ML_API_TIMEOUT", "20"))
        self.site = os.getenv("ML_SITE", "MLM").strip().upper() or "MLM"
        self.user_agent = os.getenv(
            "ML_API_USER_AGENT",
            "AutoBrillo-AI/6.4 (Mercado Libre integration)",
        )

    def _token(self) -> str:
        token = self.oauth.access_token()
        if not token:
            raise RuntimeError("Mercado Libre no está autorizado todavía.")
        return str(token)

    @staticmethod
    def _decode_response(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:1000]}
        if not isinstance(data, dict):
            return {"data": data}
        return data

    def request(self, method: str, path: str, *, authenticated: bool = True, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token()}"
        headers.setdefault("Accept", "application/json")
        headers.setdefault("User-Agent", self.user_agent)
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
        return self.request("GET", "/users/me", authenticated=True)

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Busca publicaciones de MLM.

        Primero usa el token conectado para aprovechar los permisos de la app.
        Si Mercado Libre bloquea esa modalidad por políticas/permisos, reintenta
        como búsqueda pública, que es el recurso de descubrimiento del catálogo.
        """
        query = query.strip()
        if not query:
            raise ValueError("La búsqueda no puede estar vacía.")
        limit = max(1, min(int(limit), 20))
        path = f"/sites/{self.site}/search"
        params = {"q": query, "limit": limit}

        try:
            if self.oauth.access_token():
                return self.request("GET", path, authenticated=True, params=params)
        except Exception:
            pass

        return self.request("GET", path, authenticated=False, params=params)

    def item(self, item_id: str) -> dict[str, Any]:
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Falta el ID del producto.")
        return self.request("GET", f"/items/{item_id}", authenticated=False)
