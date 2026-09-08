import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from connectors.mercadolibre_oauth import MercadoLibreOAuth

app = FastAPI(title='AutoBrillo AI OAuth Gateway', version='5.0')
oauth = MercadoLibreOAuth()

@app.get('/', response_class=PlainTextResponse)
def root():
    return 'AutoBrillo AI OAuth Gateway activo.'

@app.get('/health', response_class=PlainTextResponse)
def health():
    return 'ok'

@app.get('/oauth/mercadolibre/start')
def start_oauth():
    if not oauth.configured():
        raise HTTPException(503, 'Mercado Libre OAuth no está configurado.')
    return {'authorization_url': oauth.start()}

@app.get('/oauth/mercadolibre/callback', response_class=PlainTextResponse)
def oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(400, 'Faltan code o state.')
    try:
        oauth.exchange(code, state)
    except Exception as exc:
        raise HTTPException(400, f'No se pudo completar OAuth: {exc}')
    return 'AutoBrillo AI: Mercado Libre conectado correctamente. Ya puedes cerrar esta ventana.'
