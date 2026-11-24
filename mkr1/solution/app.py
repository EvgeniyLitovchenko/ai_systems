"""Local-only web server. Run: python app.py"""
from __future__ import annotations
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import os,json,sqlite3,threading,uuid,time,traceback,csv,io
import requests
from core import AppError,extract,aggregate,answer,stamp,MODEL,OLLAMA,suggest
import stores

ROOT=Path(__file__).resolve().parent
WORK=ROOT.parent
RUNTIME=WORK/'.runtime';RUNTIME.mkdir(exist_ok=True)
EVIDENCE=WORK/'evidence';EVIDENCE.mkdir(exist_ok=True)
LOCK=threading.Lock()
DB=RUNTIME/'history.sqlite'
with sqlite3.connect(DB) as conn:
 conn.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,title TEXT,updated TEXT,data TEXT)')

def record(kind,payload,origin='interactive'):
 event={'id':uuid.uuid4().hex,'time':stamp(),'kind':kind,'origin':origin,**payload}
 folder=EVIDENCE/('technical' if origin=='technical' else 'usage');folder.mkdir(exist_ok=True)
 with LOCK:
  with (folder/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
 return event['id']

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
 def log_message(self,fmt,*a):print('%s %s'%(stamp(),fmt%a),flush=True)
 def send_json(self,data,status=200):
  raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
  self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
  self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  route=urlparse(self.path)
  try:
   if route.path=='/api/health':
    try:
     r=requests.get(OLLAMA+'/api/tags',timeout=3);r.raise_for_status()
     ready=MODEL in [x['name'] for x in r.json().get('models',[])]
    except (requests.RequestException,ValueError):ready=False
    return self.send_json({'ready':ready,'model':MODEL,'city':'Житомир','stores':stores.context()})
   if route.path=='/api/history':
    with sqlite3.connect(DB) as conn:
     items=[{'id':i,'title':t,'updated':u} for i,t,u in conn.execute('SELECT id,title,updated FROM sessions ORDER BY updated DESC LIMIT 40')]
    return self.send_json({'sessions':items})
   if route.path=='/api/session':
    sid=parse_qs(route.query).get('id',[''])[0]
    with sqlite3.connect(DB) as conn:row=conn.execute('SELECT data FROM sessions WHERE id=?',(sid,)).fetchone()
    return self.send_json(json.loads(row[0]) if row else {'error':'Сесію не знайдено'},200 if row else 404)
   if route.path=='/api/measurements':
    path=EVIDENCE/'usage'/'measurements.jsonl'
    return self.send_json({'records':[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []})
   if route.path.startswith('/api/'):return self.send_json({'error':'Не знайдено'},404)
   return super().do_GET()
  except (OSError,ValueError) as exc:return self.send_json({'error':str(exc)},500)
 def do_POST(self):
  path=urlparse(self.path).path
  origin='technical' if self.headers.get('X-Usage-Origin')=='technical' else 'interactive'
  try:
   web_origin=self.headers.get('Origin')
   if web_origin and urlparse(web_origin).netloc!=self.headers.get('Host'):
    return self.send_json({'error':'Запит дозволений лише з локального застосунку.'},403)
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=350000:return self.send_json({'error':'Завеликий або порожній запит.'},400)
   data=json.loads(self.rfile.read(size))
   if not isinstance(data,dict):raise AppError('Очікується JSON-об’єкт.')
   if path=='/api/extract':
    result=extract(data.get('text',''));result['shopping']=aggregate(result['recipes'])
    result['run_id']=record('extract',{'input':data.get('text',''),'output':result},origin)
    return self.send_json(result)
   if path=='/api/suggest':
    result=suggest(data.get('ingredients',[]),str(data.get('source_text','')))
    result['run_id']=record('suggest',{'input':data.get('ingredients',[]),'output':result},origin)
    return self.send_json(result)
   if path=='/api/aggregate':return self.send_json({'shopping':aggregate(data.get('recipes',[]),data.get('multipliers',{}))})
   if path=='/api/prices':
    ingredients=data.get('ingredients',[])
    if not isinstance(ingredients,list) or len(ingredients)>40:raise AppError('Оновлюйте ціни не більше ніж для 40 продуктів за раз.')
    started=time.perf_counter();result=stores.compare(ingredients,bool(data.get('refresh')))
    result['seconds']=round(time.perf_counter()-started,2)
    result['run_id']=record('prices',{'ingredients':ingredients,'output':result},origin)
    return self.send_json(result)
   if path=='/api/chat':
    context=data.get('context') if data.get('mode')=='recipe' else None
    result=answer(data.get('messages'),context)
    result['run_id']=record('chat',{'mode':data.get('mode'),'input':data.get('messages',[])[-1:],'output':result},origin)
    return self.send_json(result)
   if path=='/api/product':return self.send_json(stores.import_product(data.get('url',''),data.get('store','')))
   if path=='/api/session':
    sid=str(data.get('id') or uuid.uuid4().hex)[:60]
    state=data.get('data')
    if not isinstance(state,dict):raise AppError('Немає даних для збереження.')
    title=str(data.get('title','Список покупок'))[:150]
    with sqlite3.connect(DB) as conn:
     conn.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)',(sid,title,stamp(),json.dumps(state,ensure_ascii=False)))
    return self.send_json({'id':sid,'saved':True})
   if path=='/api/delete-session':
    with sqlite3.connect(DB) as conn:conn.execute('DELETE FROM sessions WHERE id=?',(str(data.get('id','')),))
    return self.send_json({'deleted':True})
   if path=='/api/measurement':
    before=float(data.get('before_seconds',0));after=float(data.get('after_seconds',0))
    if not (0<before<86400 and 0<after<86400):raise AppError('Вкажіть додатний виміряний час до і після.')
    item={'time':stamp(),'case':str(data.get('case',''))[:150], 'before_seconds':before,'after_seconds':after,
     'saved_percent':round((before-after)/before*100,2),'source':'user_entered_measurement',
     'notes':str(data.get('notes',''))[:1500],'linked_run_id':str(data.get('run_id',''))[:60]}
    folder=EVIDENCE/'usage';folder.mkdir(exist_ok=True)
    with LOCK:
     with (folder/'measurements.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
    return self.send_json(item)
   return self.send_json({'error':'Не знайдено'},404)
  except (AppError,ValueError,KeyError,TypeError) as exc:
   record('error',{'route':path,'message':str(exc)},origin)
   return self.send_json({'error':str(exc)},400)
  except Exception:
   traceback.print_exc();return self.send_json({'error':'Внутрішня помилка. Деталі є в консолі сервера.'},500)

if __name__=='__main__':
 port=int(os.environ.get('PORT','8765'))
 print(f'Смак & Кошик: http://127.0.0.1:{port}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
