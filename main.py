import hmac
import os
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from autobrillo import Product, SalesAgent
from brillo import Brillo
from connectors.mercadolibre_oauth import MercadoLibreOAuth
from connectors.mercadolibre_api import MercadoLibreAPI
from goal_agent import GoalAgent
from security import RateLimiter, constant_time_equal, redact

app = FastAPI(title='AutoBrillo AI API', version='7.1')
oauth = MercadoLibreOAuth()
ml_api = MercadoLibreAPI(oauth)
agent = SalesAgent()
brillo = Brillo(agent)
goals = GoalAgent(agent.memory)
api_limiter = RateLimiter(limit=int(os.getenv('AUTOBRILLO_RATE_LIMIT','60')), window_seconds=60)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

app.add_middleware(SecurityHeadersMiddleware)

class LearnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    label: str = Field(min_length=1, max_length=200)
class ProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300); price: float = Field(gt=0); cost: float = Field(default=0, ge=0); commission: float = Field(default=0, ge=0); shipping_cost: float = Field(default=0, ge=0); fixed_fee: float = Field(default=0, ge=0); tax_rate: float = Field(default=0, ge=0, le=1); url: str = ''
class PermissionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50); enabled: bool = True
class GoalRequest(BaseModel): text: str = Field(min_length=3, max_length=1000)
class BrilloRequest(BaseModel): command: str = Field(min_length=1, max_length=1000)

def rate_limit(request: Request):
    forwarded = request.headers.get('x-forwarded-for','').split(',')[0].strip()
    key = forwarded or (request.client.host if request.client else 'unknown')
    if not api_limiter.allow(key):
        raise HTTPException(429, 'Demasiadas solicitudes. Intenta nuevamente en un momento.')

def require_admin(x_admin_key: str | None = Header(default=None)):
    expected=os.getenv('AUTOBRILLO_ADMIN_KEY','')
    if not expected: raise HTTPException(503,'API administrativa no configurada.')
    if not constant_time_equal(x_admin_key, expected): raise HTTPException(401,'No autorizado.')

def require_webhook_key(x_autobrillo_webhook_key: str | None = Header(default=None)):
    expected=os.getenv('AUTOBRILLO_WEBHOOK_KEY','')
    if not expected: raise HTTPException(503,'Webhook seguro no configurado.')
    if not constant_time_equal(x_autobrillo_webhook_key, expected): raise HTTPException(401,'Webhook no autorizado.')

def persistence_status():
    return {'postgres_configured':oauth.database_configured(),'token_storage':'postgresql' if oauth.database_configured() else 'local_fallback'}

@app.get('/', response_class=HTMLResponse)
def root():
    return '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Brillo · AutoBrillo AI</title><style>body{margin:0;font-family:system-ui;background:#0b1020;color:#f4f7ff}main{max-width:900px;margin:auto;padding:28px}.card{background:#151d32;border:1px solid #293451;border-radius:18px;padding:20px;margin:14px 0}h1{margin-bottom:4px}small{color:#aab5cf}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}button{width:100%;padding:16px;border:0;border-radius:12px;background:#263454;color:white;font-size:16px;cursor:pointer}textarea{width:100%;box-sizing:border-box;min-height:90px;background:#0d1426;color:white;border:1px solid #34415f;border-radius:12px;padding:12px;font-size:16px}pre{white-space:pre-wrap;word-break:break-word;background:#0b1222;padding:14px;border-radius:12px}</style></head><body><main><h1>✨ Brillo</h1><small>AutoBrillo AI · Brillo + Tygo</small><div class="card"><h2>¿Qué hacemos?</h2><textarea id="cmd" placeholder="Ejemplo: productos"></textarea><button onclick="send()">🚀 Ejecutar orden</button></div><div class="card"><h2>Acciones</h2><div class="grid"><button onclick="oauth()">🔗 Conectar Mercado Libre</button><button onclick="status()">🟢 Estado del sistema</button><button onclick="plan()">🧠 Plan de Tygo</button></div><p><small>El ciclo seguro se ejecuta automáticamente al dar una orden. Las publicaciones, compras, cobros y transferencias siguen bloqueadas hasta contar con conectores y permisos oficiales.</small></p></div><div class="card"><h2>Resultado</h2><pre id="out">Brillo está listo. Escribe una orden.</pre></div></main><script>const out=document.getElementById('out');function show(x){out.textContent=typeof x==='string'?x:JSON.stringify(x,null,2)}async function call(url,opt){try{let r=await fetch(url,opt);let t=await r.text();try{show(JSON.parse(t))}catch{show(t)}}catch(e){show('Error de conexión: '+e)}}function oauth(){location.href='/oauth/mercadolibre/start'}function status(){call('/api/status')}function plan(){call('/api/plan')}function send(){let c=document.getElementById('cmd').value.trim();if(!c)return show('Escribe una orden.');show('Brillo + Tygo están procesando la orden...');call('/api/brillo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})})}</script></body></html>'''

@app.get('/health')
def health(): return {'status':'ok','service':'AutoBrillo AI','version':'v7.1','brain_ready':agent.brain.ready,'brillo_ready':True,'mercadolibre_configured':oauth.configured(),**persistence_status()}
@app.get('/api/status', dependencies=[Depends(rate_limit)])
def status(): return {'service':'AutoBrillo AI','version':'v7.1','brain_ready':agent.brain.ready,'products':len(agent.catalog.products),'active_goals':len(goals.list_active()),'dry_run':agent.dry_run,'kill_switch':agent.kill,'brillo':'ready','tygo':'ready','mercadolibre_configured':oauth.configured(),**persistence_status()}

@app.get('/api/mercadolibre/me', dependencies=[Depends(require_admin), Depends(rate_limit)])
def mercadolibre_me():
    try: return ml_api.me()
    except Exception as exc: raise HTTPException(400,f'No se pudo consultar Mercado Libre: {redact(exc)}') from None
@app.get('/api/mercadolibre/search', dependencies=[Depends(rate_limit)])
def mercadolibre_search(q: str, limit: int=5):
    if not 1 <= limit <= 50: raise HTTPException(400,'limit debe estar entre 1 y 50.')
    try: return ml_api.search(q,limit)
    except Exception as exc: raise HTTPException(400,f'No se pudo buscar en Mercado Libre: {redact(exc)}') from None
@app.get('/api/mercadolibre/item/{item_id}', dependencies=[Depends(rate_limit)])
def mercadolibre_item(item_id: str):
    if len(item_id) > 100 or any(ch in item_id for ch in '<>\"\''): raise HTTPException(400,'Identificador de producto inválido.')
    try: return ml_api.item(item_id)
    except Exception as exc: raise HTTPException(400,f'No se pudo consultar el producto: {redact(exc)}') from None

@app.post('/api/brillo', dependencies=[Depends(rate_limit)])
def brillo_command(request: BrilloRequest):
    try:
        result = brillo.respond(request.command)
        if result.get('ok') and result.get('intent', {}).get('intent') in ('source', 'source_and_sell'):
            count = int(result['intent']['product_count'])
            result['execution'] = agent.run_cycle(count)
            result['status'] = 'executed_safe_cycle'
            result['next'] = 'verificar costos de proveedor; después preparar publicación/venta mediante conectores oficiales autorizados'
        return result
    except Exception as exc: raise HTTPException(400,f'Brillo no pudo procesar la orden: {redact(exc)}') from None

@app.get('/api/plan', dependencies=[Depends(rate_limit)])
def plan(limit:int|None=None):
    if limit is not None and not 1<=limit<=50: raise HTTPException(400,'limit debe estar entre 1 y 50.')
    count = limit if limit is not None else int(brillo.understand('productos')['product_count'])
    return {'tygo_decision':brillo.understand('productos'),'tasks':agent.plan(count)}

@app.post('/api/cycle', dependencies=[Depends(rate_limit)])
def cycle(limit:int|None=None):
    if limit is not None and not 1<=limit<=50: raise HTTPException(400,'limit debe estar entre 1 y 50.')
    count = limit if limit is not None else int(brillo.understand('productos')['product_count'])
    return {'tygo_decision':brillo.understand('productos'),'cycle':agent.run_cycle(count)}

@app.post('/api/goal', dependencies=[Depends(require_admin), Depends(rate_limit)])
def create_goal(request:GoalRequest):
    try: goal=goals.create(request.text); plan=goals.plan(goal); execution=goals.execute_safe(goal,agent)
    except ValueError as exc: raise HTTPException(400,redact(exc))
    return {'ok':True,'goal':goal.__dict__,'plan':plan,'execution':execution}
@app.get('/api/goals', dependencies=[Depends(require_admin), Depends(rate_limit)])
def list_goals(): return {'goals':goals.list_active()}
@app.post('/api/learn', dependencies=[Depends(require_admin), Depends(rate_limit)])
def learn(request:LearnRequest): agent.learn(request.text,request.label); return {'ok':True,'message':'Aprendizaje guardado.','brain_ready':agent.brain.ready}
@app.get('/api/products', dependencies=[Depends(require_admin), Depends(rate_limit)])
def products(): return {'products':[p.__dict__ for p in agent.catalog.products]}
@app.post('/api/products', dependencies=[Depends(require_admin), Depends(rate_limit)])
def add_product(request:ProductRequest):
    try:
        product=Product(request.name,request.price,request.cost,request.commission,request.url,shipping_cost=request.shipping_cost,fixed_fee=request.fixed_fee,tax_rate=request.tax_rate,cost_known=request.cost>0); agent.catalog.add(product)
    except ValueError as exc: raise HTTPException(400,redact(exc))
    return {'ok':True,'product':product.__dict__}
@app.post('/api/permissions', dependencies=[Depends(require_admin), Depends(rate_limit)])
def set_permission(request:PermissionRequest):
    try: agent.memory.set_permission(request.name,request.enabled)
    except ValueError as exc: raise HTTPException(400,redact(exc))
    return {'ok':True,'name':request.name,'enabled':request.enabled}

@app.get('/oauth/mercadolibre/start', dependencies=[Depends(rate_limit)])
def start_oauth():
    if not oauth.configured(): raise HTTPException(503,'Mercado Libre OAuth no está configurado.')
    return RedirectResponse(url=oauth.start(),status_code=302)
@app.get('/oauth/mercadolibre/callback', response_class=PlainTextResponse, dependencies=[Depends(rate_limit)])
def oauth_callback(code:str|None=None,state:str|None=None):
    if not code or not state: raise HTTPException(400,'Faltan code o state.')
    try: oauth.exchange(code,state)
    except Exception as exc: raise HTTPException(400,f'No se pudo completar OAuth: {redact(exc)}') from None
    return 'AutoBrillo AI: Mercado Libre conectado correctamente. Ya puedes cerrar esta ventana.'
@app.post('/webhooks/mercadolibre',status_code=200, dependencies=[Depends(require_webhook_key), Depends(rate_limit)])
async def mercadolibre_webhook(payload:dict):
    agent.memory.remember('mercadolibre_webhook',{'received':True,'keys':sorted(payload.keys())[:20]},'received')
    return {'ok':True}
