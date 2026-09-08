import hmac
import os
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from autobrillo import Product, SalesAgent
from connectors.mercadolibre_oauth import MercadoLibreOAuth
from goal_agent import GoalAgent

app = FastAPI(title='AutoBrillo AI API', version='6.0')
oauth = MercadoLibreOAuth()
agent = SalesAgent()
goals = GoalAgent(agent.memory)

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
    name: str = Field(min_length=1, max_length=50)
    enabled: bool = True

class GoalRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)

def require_admin(x_admin_key: str | None = Header(default=None)):
    expected = os.getenv('AUTOBRILLO_ADMIN_KEY', '')
    if not expected:
        raise HTTPException(503, 'API administrativa no configurada.')
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(401, 'No autorizado.')

@app.get('/', response_class=PlainTextResponse)
def root():
    return 'AutoBrillo AI API activa.'

@app.get('/health', response_class=PlainTextResponse)
def health():
    return 'ok'

@app.get('/api/status')
def status():
    return {
        'service': 'AutoBrillo AI',
        'version': 'v6.0',
        'brain_ready': agent.brain.ready,
        'products': len(agent.catalog.products),
        'active_goals': len(goals.list_active()),
        'dry_run': agent.dry_run,
        'kill_switch': agent.kill,
    }

@app.get('/api/plan', dependencies=[Depends(require_admin)])
def plan(limit: int = 5):
    if not 1 <= limit <= 50:
        raise HTTPException(400, 'limit debe estar entre 1 y 50.')
    return {'tasks': agent.plan(limit)}

@app.post('/api/cycle', dependencies=[Depends(require_admin)])
def cycle(limit: int = 5):
    if not 1 <= limit <= 50:
        raise HTTPException(400, 'limit debe estar entre 1 y 50.')
    return agent.run_cycle(limit)

@app.post('/api/goal', dependencies=[Depends(require_admin)])
def create_goal(request: GoalRequest):
    try:
        goal = goals.create(request.text)
        plan = goals.plan(goal)
        execution = goals.execute_safe(goal, agent)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'goal': goal.__dict__, 'plan': plan, 'execution': execution}

@app.get('/api/goals', dependencies=[Depends(require_admin)])
def list_goals():
    return {'goals': goals.list_active()}

@app.post('/api/learn', dependencies=[Depends(require_admin)])
def learn(request: LearnRequest):
    agent.learn(request.text, request.label)
    return {'ok': True, 'message': 'Aprendizaje guardado.', 'brain_ready': agent.brain.ready}

@app.get('/api/products', dependencies=[Depends(require_admin)])
def products():
    return {'products': [p.__dict__ for p in agent.catalog.products]}

@app.post('/api/products', dependencies=[Depends(require_admin)])
def add_product(request: ProductRequest):
    try:
        product = Product(request.name, request.price, request.cost, request.commission, request.url)
        agent.catalog.add(product)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'product': product.__dict__}

@app.post('/api/permissions', dependencies=[Depends(require_admin)])
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
    return RedirectResponse(url=oauth.start(), status_code=302)

@app.get('/oauth/mercadolibre/callback', response_class=PlainTextResponse)
def oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(400, 'Faltan code o state.')
    try:
        oauth.exchange(code, state)
    except Exception as exc:
        raise HTTPException(400, f'No se pudo completar OAuth: {exc}')
    return 'AutoBrillo AI: Mercado Libre conectado correctamente. Ya puedes cerrar esta ventana.'

@app.post('/webhooks/mercadolibre', status_code=200)
async def mercadolibre_webhook(payload: dict):
    agent.memory.remember('mercadolibre_webhook', {'received': True, 'keys': sorted(payload.keys())[:20]}, 'received')
    return {'ok': True}
