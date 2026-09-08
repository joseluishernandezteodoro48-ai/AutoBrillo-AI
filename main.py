import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from autobrillo import Product, SalesAgent
from connectors.mercadolibre_oauth import MercadoLibreOAuth

app = FastAPI(title='AutoBrillo AI API', version='5.1')
oauth = MercadoLibreOAuth()
agent = SalesAgent()


class LearnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    label: str = Field(min_length=1, max_length=200)


class ProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    price: float = Field(gt=0)
    cost: float = Field(default=0, ge=0)
    commission: float = Field(default=0, ge=0)
    url: str = ''


class PermissionRequest(BaseModel):
    name: str
    enabled: bool = True


@app.get('/', response_class=PlainTextResponse)
def root():
    return 'AutoBrillo AI API activa.'


@app.get('/health', response_class=PlainTextResponse)
def health():
    return 'ok'


@app.get('/api/status')
def status():
    return agent.status()


@app.get('/api/plan')
def plan(limit: int = 5):
    if not 1 <= limit <= 50:
        raise HTTPException(400, 'limit debe estar entre 1 y 50.')
    return {'tasks': agent.plan(limit)}


@app.post('/api/cycle')
def cycle(limit: int = 5):
    if not 1 <= limit <= 50:
        raise HTTPException(400, 'limit debe estar entre 1 y 50.')
    return agent.run_cycle(limit)


@app.post('/api/learn')
def learn(request: LearnRequest):
    agent.learn(request.text, request.label)
    return {'ok': True, 'message': 'Aprendizaje guardado.', 'brain_ready': agent.brain.ready}


@app.get('/api/products')
def products():
    return {'products': [p.__dict__ for p in agent.catalog.products]}


@app.post('/api/products')
def add_product(request: ProductRequest):
    try:
        product = Product(
            request.name,
            request.price,
            request.cost,
            request.commission,
            request.url,
        )
        agent.catalog.add(product)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'product': product.__dict__}


@app.post('/api/permissions')
def set_permission(request: PermissionRequest):
    try:
        agent.memory.set_permission(request.name, request.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'name': request.name, 'enabled': request.enabled}


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
