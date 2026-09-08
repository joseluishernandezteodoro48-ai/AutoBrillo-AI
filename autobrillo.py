import argparse, html, json, os, re, sqlite3, time
from dataclasses import asdict, dataclass
from typing import Optional
from model import AutoBrilloBrain

DB=os.environ.get('AUTOBRILLO_DB','autobrillo.db')
PERMISSIONS=('web','social','sales','payments','marketing','analytics','products')

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
 name:str; price:float; cost:float=0; commission:float=0; url:str=''; active:bool=True; score:float=0
 @property
 def commission_value(self):return self.price*self.commission if 0<self.commission<1 else self.commission
 @property
 def estimated_profit(self):return max(0,self.price-self.cost)+self.commission_value

class Catalog:
 def __init__(self,path='catalog.json'):self.path=path;self.products=[];self.load()
 def load(self):
  if os.path.exists(self.path):
   with open(self.path,encoding='utf8') as f:self.products=[Product(**x) for x in json.load(f)]
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
 """Adaptadores sin secretos. Requieren variables de entorno y APIs oficiales."""
 def __init__(self,name,permission,env_vars):self.name=name;self.permission=permission;self.env_vars=env_vars
 def configured(self):return all(os.getenv(x) for x in self.env_vars)
 def status(self):return {'name':self.name,'permission':self.permission,'configured':self.configured()}

class SalesAgent:
 def __init__(self):
  self.memory=Memory();self.brain=AutoBrilloBrain();self.catalog=Catalog();self.site_builder=SiteBuilder();self.dry_run=os.getenv('AUTOBRILLO_DRY_RUN','true').lower()!='false';self.kill=os.getenv('AUTOBRILLO_KILL_SWITCH','false').lower()=='true'
  self.connectors=[Connector('Meta/Facebook','social',('META_ACCESS_TOKEN','META_PAGE_ID')),Connector('Mercado Libre','products',('ML_ACCESS_TOKEN','ML_USER_ID')),Connector('Analytics','analytics',('ANALYTICS_API_KEY',))]
 def learn(self,text,label):self.brain.add_examples([{'text':text,'label':label}]);self.memory.remember('learning',{'text':text,'label':label},'stored')
 def record_result(self,action,result,value=0,product=None):self.memory.remember('sales_result',{'action':action,'value':value,'product':product},result);self.memory.metric(product,action,value)
 def create_page(self,name):
  p=next((x for x in self.catalog.products if x.name==name),None)
  if not p:raise ValueError('Producto no encontrado')
  path=self.site_builder.build(p);self.memory.remember('page_created',{'product':p.name,'path':path},'created');return path
 def score_products(self):
  for p in self.catalog.products:
   m=self.memory.metrics(p.name);clicks=m.get('click',{}).get('count',0);sales=m.get('sale',{}).get('count',0);rev=m.get('commission',{}).get('value',0);conv=sales/clicks if clicks else 0;profit=min(p.estimated_profit/max(p.price,1),1);p.score=round(.45*profit+.35*min(conv,1)+.20*min(rev/1000,1),6)
  self.catalog.save();self.memory.remember('scoring',{'products':len(self.catalog.products)},'completed')
 def plan(self,limit=5):
  self.score_products();tasks=[]
  for p in self.catalog.best(limit):tasks.append({'action':'create_page','product':p.name,'priority':p.score})
  if self.memory.allowed('marketing'):
   for p in self.catalog.best(limit):tasks.append({'action':'prepare_marketing','product':p.name,'priority':p.score*.9})
  return sorted(tasks,key=lambda x:x['priority'],reverse=True)
 def execute(self,task):
  if self.kill:raise RuntimeError('KILL SWITCH activo')
  action=task['action']
  if action=='create_page':return {'ok':True,'path':self.create_page(task['product'])}
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
  return {'version':'v5','products':len(self.catalog.products),'events':len(self.memory.recent(100000)),'brain_ready':self.brain.ready,'permissions':{k:self.memory.allowed(k) for k in PERMISSIONS},'dry_run':self.dry_run,'kill_switch':self.kill,'connectors':[c.status() for c in self.connectors],'planned_tasks':len(self.plan())}

def main():
 p=argparse.ArgumentParser(description='AutoBrillo AI v5')
 s=p.add_subparsers(dest='cmd');s.add_parser('status');s.add_parser('plan');s.add_parser('cycle');s.add_parser('connectors')
 l=s.add_parser('learn');l.add_argument('text');l.add_argument('label')
 a=s.add_parser('add-product');a.add_argument('name');a.add_argument('price',type=float);a.add_argument('--cost',type=float,default=0);a.add_argument('--commission',type=float,default=0);a.add_argument('--url',default='')
 perm=s.add_parser('permission');perm.add_argument('name',choices=PERMISSIONS);perm.add_argument('enabled',type=int,choices=(0,1))
 args=p.parse_args();agent=SalesAgent()
 if args.cmd=='learn':agent.learn(args.text,args.label);print('Aprendizaje guardado')
 elif args.cmd=='add-product':agent.catalog.add(Product(args.name,args.price,args.cost,args.commission,args.url));print('Producto agregado')
 elif args.cmd=='plan':print(json.dumps(agent.plan(),ensure_ascii=False,indent=2))
 elif args.cmd=='cycle':print(json.dumps(agent.run_cycle(),ensure_ascii=False,indent=2))
 elif args.cmd=='connectors':print(json.dumps([c.status() for c in agent.connectors],ensure_ascii=False,indent=2))
 elif args.cmd=='permission':agent.memory.set_permission(args.name,bool(args.enabled));print('Permiso actualizado')
 else:print(json.dumps(agent.status(),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
