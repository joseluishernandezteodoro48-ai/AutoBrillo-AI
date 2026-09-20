"""DEPRECATED.

Este módulo es una versión antigua. Usa:
    from connectors.mercadolibre_oauth import MercadoLibreOAuth

Se mantiene solo para no romper imports accidentales.
"""
from connectors.mercadolibre_oauth import MercadoLibreOAuth  # noqa: F401

raise ImportError(
    "mercadolibre_oauth (raíz) está deprecado. "
    "Importa desde connectors.mercadolibre_oauth"
)
