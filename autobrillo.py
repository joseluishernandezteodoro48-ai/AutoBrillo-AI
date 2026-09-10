import argparse, html, json, os, re, sqlite3, time
from dataclasses import asdict, dataclass
from typing import Optional
from model import AutoBrilloBrain

DB=os.environ.get('AUTOBRILLO_DB','autobrillo.db')
PERMISSIONS=('web','social','sales','payments','marketing','analytics','products','logistics')

class Memory:
 def __init__(self,db=DB):
  self.db=db
  with sqlite3.connect(db) as c:
   c.execute('PRAGMA journal_mode=WAL')
   c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,kind TEXT,data TEXT,outcome TEXT)')
   c.execute('CREATE TABLE IF NOT EXISTS permissions(name TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0)')
   c.execute('CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,product TEXT,event TEXT,value REAL DEFAULT 0)')
 def remember(self,kind,data,outcome=None):
  with sqlite3.connect(self.db) as c:c.execute('INSERT INTO events(ts,kind,data,outcome) VALUES(?,?,?,?)',(time.time(),kind,json.dumps(data,ensure_ascii=False),outcome))
 def recent(self,limit=50):
  with sqlite3.connect(self.db) as c:r=c.execute('SELECT ts,kind,data,outcome FROM events ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
  return [{'ts':r[0],'kind':r[1],'data':json.loads(r[2]),'outcome':r[3]} for r in r]
 def set_permission(self,name,enabled=True):
  if name not in PERMISSIONS:raise ValueError('Permiso desconocido: '+name)
  with sqlite3.connect(self.db) as c:c.execute('INSERT INTO permissions(name,enabled) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled',(name,int(enabled)))
  self.remember('permission',{'name':name,'enabled':bool(enabled)},'updated')
 def allowed(self,name):
  with sqlite3.connect(self.db) as c:r=c.execute('SELECT enabled FROM permissions WHERE name=?',(name,)).fetchone()
  return bool(r and r[0])
 def metric(self,product,event,value=0):
  with sqlite3.connect(self.db) as c:c.execute('INSERT INTO metrics(ts,product,event,value) VALUES(?,?,?,?)',(time.time(),product,event,float(value)))
 def metrics(self,product=None):
  q='SELECT event,COUNT(*),COALESCE(SUM(value),0) FROM metrics';a=[]
  if product:q+=' WHERE product=?';a.append(product)
  q+=' GROUP BY event'
  with sqlite3.connect(self.db) as c:r=c.execute(q,a).fetchall()
  return {e:{'count':n,'value':v} for e,n,v in r}

@dataclass
class Product:
 name:str; price:float; cost:float=0; commission:float=0; url:str=''; active:bool=True; score:float=0; shipping_cost:float=0; fixed_fee:float=0; tax_rate:float=0; cost_known:bool=False
 @property
 def commission_value(self):return self.price*self.commission if 0<self.commission<1 else self.commission
 @property
 def tax_value(self):return self.price*max(0,self.tax_rate) if self.tax_rate<1 else max(0,self.tax_rate)
 @property
 def total_cost(self):return max(0,self.cost)+max(0,self.shipping_cost)+max(0,self.fixed_fee)+self.commission_value+self.tax_value
 @property
 def estimated_profit(self):return self.price-self.total_cost
 @property
 def margin(self):return self.estimated_profit/max(self.price,1)

@dataclass
class Order:
 order_id:str; product:str; buyer_id:str=''; supplier_id:str=''; buyer_address:dict=None; supplier_address:dict=None; status:str='pending'; tracking:str=''

class LogisticsManager:
 """Gestiona el flujo comprador -> proveedor -> envío sin exponer datos de dirección en logs."""
 def __init__(self,memory):self.memory=memory
 def _safe_address(self,address):
  if not isinstance(address,dict):raise ValueError('La dirección debe ser un objeto')
  required=('street','city','state','postal_code','country');missing=[x for x in required if not address.get(x)]
  if missing:raise ValueError('Faltan campos de dirección: '+', '.join(missing))
  return {k:str(address[k]).strip() for k in required if address.get(k)}
 def validate(self,address):
  a=self._safe_address(address);return {'valid':True,'country':a['country'],'city':a['city'],'postal_code':a['postal_code']}
 def register_order(self,order):
  if not self.memory.allowed('logistics'):raise PermissionError('Permiso logistics requerido')
  buyer=self._safe_address(order.buyer_address or {});supplier=self._safe_address(order.supplier_address or {})
  if not order.order_id:raise ValueError('order_id requerido')
  self.memory.remember('order_created',{'order_id':order.order_id,'product':order.product,'buyer_id':order.buyer_id,'supplier_id':order.supplier_id,'status':order.status},'created')
  self.memory.remember('address_validation',{'order_id':order.order_id,'buyer':self.validate(buyer),'supplier':self.validate(supplier)},'validated')
  return {'ok':True,'order_id':order.order_id,'status':order.status}
 def prepare_fulfillment(self,order_id,product):
  if not self.memory.allowed('logistics'):raise PermissionError('Permiso logistics requerido')
  self.memory.remember('fulfillment_prepared',{'order_id':order_id,'product':product},'prepared');return {'ok':True,'order_id':order_id,'next':'supplier_dispatch'}
 def update_tracking(self,order_id,tracking,status='shipped'):
  if not self.memory.allowed('logistics'):raise PermissionError('Permiso logistics requerido')
  if not tracking:raise ValueError('tracking requerido')
  self.memory.remember('shipment_update',{'order_id':order_id,'tracking':tracking,'status':status},'updated');return {'ok':True,'order_id':order_id,'tracking':tracking,'status':status}

class Catalog:
 def __init__(self,path='catalog.json'):self.path=path;self.products=[];self.load()
 def load(self):
  if os.path.exists(self.path):
   with open(self.path,encoding='utf8') as f:
    raw=json.load(f);self.products=[]
    for x in raw:
     x=dict(x)
     x.setdefault('shipping_cost',0);x.setdefault('fixed_fee',0);x.setdefault('tax_rate',0)
     x.setdefault('cost_known',bool(x.get('cost',0)))
     self.products.append(Product(**x))
 def save(self):
  with open(self.path,'w',encoding='utf8') as f:json.dump([asdict(p) for p in self.products],f,ensure_ascii=False,indent=2)
 def add(self,p):
  if any(x.name.lower()==p.name.lower() for x in self.products):raise ValueError('El producto ya existe')
  self.products.append(p);self.save()
 def best(self,n=10):return sorted((p for p in self.products if p.active),key=lambda p:(p.score,p.estimated_profit),reverse=True)[:n]

class SiteBuilder:
 def build(self,p,folder='sites'):
  os.makedirs(folder,exist_ok=True);slug=re.sub(r'[^a-z0-9]+','-',p.name.lower()).strip('-') or 'producto';path=os.path.join(folder,slug+'.html')
  name,url=html.escape(p.name),html.escape(p.url,quote=True)
  doc=f'''<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name} | AutoBrillo</title></head><body><main><h1>{name}</h1><h2>${p.price:,.2f} MXN</h2><p>Oferta seleccionada por AutoBrillo AI.</p><a href="{url}" rel="nofollow sponsored" target="_blank">Ver producto</a></main></body></html>'''
  with open(path,'w',encoding='utf8') as f:f.write(doc)
  return path

class Connector:
 def __init__(self,name,permission,env_vars):self.name=name;self.permission=permission;self.env_vars=env_vars
 def configured(self):return all(os.getenv(x) for x in self.env_vars)
 def status(self):return {'name':self.name,'permission':self.permission,'configured':self.configured()}

class SalesAgent:
 def __init__(self):
  self.memory=Memory();self.brain=AutoBrilloBrain();self.catalog=Catalog();self.site_builder=SiteBuilder();self.logistics=LogisticsManager(self.memory);self.dry_run=os.getenv('AUTOBRILLO_DRY_RUN','true').lower()!='false';self.kill=os.getenv('AUTOBRILLO_KILL_SWITCH','false').lower()=='true'
  self.connectors=[Connector('Meta/Facebook','social',('META_ACCESS_TOKEN','META_PAGE_ID')),Connector('Mercado Libre','products',('ML_ACCESS_TOKEN','ML_USER_ID')),Connector('Analytics','analytics',('ANALYTICS_API_KEY',)),Connector('Logistics provider','logistics',('LOGISTICS_API_KEY',))]
 def learn(self,text,label):
  result=self.brain.add_examples([{'text':text,'label':label}]);self.memory.remember('learning',{'text':text,'label':label},'stored');return result
 def record_result(self,action,result,value=0,product=None):self.memory.remember('sales_result',{'action':action,'value':value,'product':product},result);self.memory.metric(product,action,value)
 def create_page(self,name):
  p=next((x for x in self.catalog.products if x.name==name),None)
  if not p:raise ValueError('Producto no encontrado')
  path=self.site_builder.build(p);self.memory.remember('page_created',{'product':p.name,'path':path},'created');return path
 def score_products(self):
  for p in self.catalog.products:
   m=self.memory.metrics(p.name);clicks=m.get('click',{}).get('count',0);sales=m.get('sale',{}).get('count',0);rev=m.get('commission',{}).get('value',0);conv=sales/clicks if clicks else 0
   margin=max(0,min(p.margin,1)) if p.cost_known else 0
   data_quality=1.0 if p.cost_known else 0.15
   p.score=round(.45*margin+.25*min(conv,1)+.15*min(rev/1000,1)+.15*data_quality,6)
  self.catalog.save();self.memory.remember('scoring',{'products':len(self.catalog.products)},'completed')
 def think(self):
  candidates=[]
  for p in self.catalog.products:
   m=self.memory.metrics(p.name);clicks=m.get('click',{}).get('count',0);sales=m.get('sale',{}).get('count',0)
   risk=0.75 if not p.cost_known else 0.2
   candidates.append({'name':p.name,'price':p.price,'estimated_profit':p.estimated_profit if p.cost_known else 0,'commission_value':p.commission_value,'clicks':clicks,'sales':sales,'trend':min(1.0,max(0.0,p.score)),'confidence':0.8 if p.cost_known else 0.2,'risk':risk,'cost_known':p.cost_known,'margin':p.margin if p.cost_known else None})
  decision=self.brain.think({'candidates':candidates});self.memory.remember('decision',decision,'computed');return decision
 def plan(self,limit=5):
  self.score_products();decision=self.think();tasks=[]
  ordered=[x.get('name') for x in decision.get('alternatives',[]) if x.get('name')]
  for name in ordered[:limit]:
   item=next((p for p in self.catalog.products if p.name==name and p.active),None)
   if item:
    selected=next((x for x in decision['alternatives'] if x.get('name')==name),{});ready=item.cost_known and item.estimated_profit>0
    tasks.append({'action':'research_cost' if not item.cost_known else 'prepare_sale','product':name,'priority':selected.get('score',item.score),'estimated_profit':round(item.estimated_profit,2) if item.cost_known else None,'margin':round(item.margin,4) if item.cost_known else None,'ready_to_sell':ready,'reason':'falta costo real del proveedor' if not item.cost_known else ('margen positivo' if ready else 'margen no rentable')})
    if ready:tasks.append({'action':'create_page','product':name,'priority':selected.get('score',item.score)*.95,'estimated_profit':round(item.estimated_profit,2),'margin':round(item.margin,4)})
  if self.memory.allowed('marketing'):
   for p in self.catalog.best(limit):
    if p.cost_known and p.estimated_profit>0:tasks.append({'action':'prepare_marketing','product':p.name,'priority':p.score*.9})
  return sorted(tasks,key=lambda x:x['priority'],reverse=True)
 def execute(self,task):
  if self.kill:raise RuntimeError('KILL SWITCH activo')
  action=task['action']
  if action=='create_page':return {'ok':True,'path':self.create_page(task['product'])}
  if action=='research_cost':
   self.memory.remember('cost_research_needed',{'product':task['product']},'blocked_until_cost_known');return {'ok':True,'product':task['product'],'status':'needs_supplier_cost'}
  if action=='prepare_sale':
   if not task.get('ready_to_sell'):return {'ok':False,'product':task['product'],'status':'not_profitable'}
   self.memory.remember('sale_prepared',{'product':task['product']},'ready_to_sell');return {'ok':True,'product':task['product'],'status':'ready_to_sell','dry_run':self.dry_run}
  if action=='prepare_marketing':self.memory.remember('marketing_draft',{'product':task['product']},'prepared');return {'ok':True,'draft':task['product']}
  if action in ('publish','charge','purchase','transfer_money'):raise PermissionError('Acción financiera/publicación requiere un conector oficial y permiso explícito')
  raise ValueError('Acción desconocida')
 def run_cycle(self,limit=5):
  if self.kill:return {'stopped':True,'reason':'kill_switch'}
  tasks=self.plan(limit);results=[]
  for t in tasks:
   try:results.append({'task':t,'result':self.execute(t)})
   except Exception as e:results.append({'task':t,'error':str(e)})
  self.memory.remember('cycle',{'tasks':len(tasks),'dry_run':self.dry_run},'completed');return {'dry_run':self.dry_run,'tasks':results}
 def status(self):
  return {'version':'v6.0','products':len(self.catalog.products),'events':len(self.memory.recent(100000)),'brain_ready':self.brain.ready,'brain_stats':self.brain.stats(),'permissions':{k:self.memory.allowed(k) for k in PERMISSIONS},'dry_run':self.dry_run,'kill_switch':self.kill,'connectors':[c.status() for c in self.connectors],'planned_tasks':len(self.plan())}

def main():
 p=argparse.ArgumentParser(description='AutoBrillo AI v6.0');s=p.add_subparsers(dest='cmd');s.add_parser('status');s.add_parser('plan');s.add_parser('cycle');s.add_parser('connectors');s.add_parser('think')
 l=s.add_parser('learn');l.add_argument('text');l.add_argument('label')
 a=s.add_parser('add-product');a.add_argument('name');a.add_argument('price',type=float);a.add_argument('--cost',type=float,default=0);a.add_argument('--commission',type=float,default=0);a.add_argument('--shipping',type=float,default=0);a.add_argument('--fixed-fee',type=float,default=0);a.add_argument('--tax-rate',type=float,default=0);a.add_argument('--url',default='')
 perm=s.add_parser('permission');perm.add_argument('name',choices=PERMISSIONS);perm.add_argument('enabled',type=int,choices=(0,1))
 args=p.parse_args();agent=SalesAgent()
 if args.cmd=='learn':agent.learn(args.text,args.label);print('Aprendizaje guardado')
 elif args.cmd=='add-product':agent.catalog.add(Product(args.name,args.price,args.cost,args.commission,args.url,shipping_cost=args.shipping,fixed_fee=args.fixed_fee,tax_rate=args.tax_rate,cost_known=True));print('Producto agregado')
 elif args.cmd=='plan':print(json.dumps(agent.plan(),ensure_ascii=False,indent=2))
 elif args.cmd=='think':print(json.dumps(agent.think(),ensure_ascii=False,indent=2))
 elif args.cmd=='cycle':print(json.dumps(agent.run_cycle(),ensure_ascii=False,indent=2))
 elif args.cmd=='connectors':print(json.dumps([c.status() for c in agent.connectors],ensure_ascii=False,indent=2))
 elif args.cmd=='permission':agent.memory.set_permission(args.name,bool(args.enabled));print('Permiso actualizado')
 else:print(json.dumps(agent.status(),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
