"""Construcción de payloads de publicación para Mercado Libre.

No publica nada por sí solo. Solo arma el cuerpo que exige la API oficial.
category_id debe ser válido para el sitio (MLM por defecto).
"""
from __future__ import annotations

import os
import re
from typing import Any


def _slug_title(name: str, max_len: int = 60) -> str:
    title = re.sub(r"\s+", " ", str(name).strip())
    return title[:max_len]


def build_item_payload(
    *,
    title: str,
    price: float,
    available_quantity: int = 1,
    category_id: str | None = None,
    currency_id: str | None = None,
    condition: str = "new",
    buying_mode: str = "buy_it_now",
    listing_type_id: str = "gold_special",
    pictures: list[dict[str, str]] | None = None,
    description: str | None = None,
    attributes: list[dict[str, Any]] | None = None,
    shipping_mode: str = "me2",
) -> dict[str, Any]:
    """
    Arma un payload mínimo válido para POST /items.

    category_id:
      - Si no se pasa, usa ML_DEFAULT_CATEGORY_ID del entorno.
      - Debe existir en el catálogo de ML del sitio configurado.
    """
    site = os.getenv("ML_SITE", "MLM").strip().upper() or "MLM"
    currency = currency_id or ("MXN" if site == "MLM" else "USD")
    cat = (category_id or os.getenv("ML_DEFAULT_CATEGORY_ID", "")).strip()
    if not cat:
        raise ValueError(
            "Falta category_id. Configura ML_DEFAULT_CATEGORY_ID o pásalo explícitamente. "
            "Ejemplo MLM: MLM1055 (Celulares y Teléfonos) — verifica en el panel de ML."
        )
    if price <= 0:
        raise ValueError("price debe ser > 0")
    qty = max(1, int(available_quantity))

    payload: dict[str, Any] = {
        "title": _slug_title(title),
        "category_id": cat,
        "price": round(float(price), 2),
        "currency_id": currency,
        "available_quantity": qty,
        "buying_mode": buying_mode,
        "condition": condition,
        "listing_type_id": listing_type_id,
    }
    if pictures:
        payload["pictures"] = pictures
    if attributes:
        payload["attributes"] = attributes
    if description:
        payload["description"] = {"plain_text": str(description)[:50000]}

    # Envío: modo me2 es el más común en ML México; el vendedor debe tenerlo activo.
    payload["shipping"] = {"mode": shipping_mode, "local_pick_up": False, "free_shipping": False}
    return payload


def product_to_payload(
    product: Any,
    *,
    category_id: str | None = None,
    quantity: int = 1,
    picture_url: str | None = None,
) -> dict[str, Any]:
    """Convierte un Product de AutoBrillo en payload de publicación ML."""
    pictures = None
    url = picture_url or getattr(product, "url", "") or ""
    # ML exige picture source por URL pública; solo incluir si parece URL http(s)
    if isinstance(url, str) and url.startswith(("http://", "https://")) and "mercadolibre" not in url:
        # Evitar usar permalink de ML de terceros como imagen propia
        pictures = [{"source": url}]

    desc = (
        f"{getattr(product, 'name', '')}\n"
        f"Publicado con AutoBrillo AI.\n"
        f"Precio de referencia: {getattr(product, 'price', 0)}"
    )
    return build_item_payload(
        title=str(getattr(product, "name", "")),
        price=float(getattr(product, "price", 0) or 0),
        available_quantity=quantity,
        category_id=category_id,
        description=desc,
        pictures=pictures,
    )
