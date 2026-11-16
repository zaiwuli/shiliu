"""Search the external AVDB table and submit downloads through its API."""
import os,json,csv,sqlite3
from datetime import datetime,timezone
from fastapi import Query
from pathlib import Path
from urllib.parse import urlparse
from contextlib import contextmanager
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine,text,Column,BigInteger,Text,Integer,Date
from sqlalchemy.orm import Session,declarative_base
from app.core.config import config_manager,data_path

Base=declarative_base()
class Target(Base):
 __tablename__='article'
 tid=Column(BigInteger,primary_key=True)
 title=Column(Text)
 website=Column(Text)
 section=Column(Text)
 category=Column(Text)
 size=Column(Integer)
 publish_date=Column(Date)
 preview_images=Column(Text)
 detail_url=Column(Text)

cfg=config_manager.get()
database_url=cfg.DATABASE_URL or f'postgresql://{cfg.POSTGRES_USER}:{cfg.POSTGRES_PASSWORD}@{cfg.POSTGRES_HOST}:{cfg.POSTGRES_PORT}/{cfg.POSTGRES_DB}'
read_engine=create_engine(database_url,connect_args={'options':'-c default_transaction_read_only=on -c statement_timeout=20000','connect_timeout':5},pool_pre_ping=True)
@contextmanager
def session_scope():
 with Session(read_engine) as db:
  try:yield db
  finally:db.rollback()

def links(value):
 if not value:return []
 if isinstance(value,list):return [str(v) for v in value if v]
 value=str(value).strip()
 if value.startswith('['):
  try:return links(json.loads(value))
  except ValueError:pass
 if value.startswith('{') and value.endswith('}'):
  return [v for v in next(csv.reader([value[1:-1]],escapechar='\\')) if v and v!='NULL']
 return [v.strip() for v in value.replace('\r','').replace('\n',',').split(',') if v.strip()]

router = APIRouter(prefix='/api/avdb')

settings_file=Path(data_path)/'avdb-settings.json'
def connection_settings():
 data={'url':os.getenv('AVDB_URL',''),'api_key':os.getenv('AVDB_API_KEY',''),'mode':'rules','downloader':'','save_path':''}
 if settings_file.exists():data.update(json.loads(settings_file.read_text(encoding='utf-8')))
 return data
class ConnectionSettings(BaseModel):
 url:str
 api_key:str=''
 mode:str='rules'
 downloader:str=''
 save_path:str=''
@router.get('/settings')
def get_settings():
 data=connection_settings()
 return {**data,'api_key':'','key_configured':bool(data['api_key'])}
@router.post('/settings')
def save_settings(body:ConnectionSettings):
 data=body.model_dump();data['url']=body.url.strip().rstrip('/')
 parsed=urlparse(data['url'])
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise HTTPException(422,'请输入有效的 AVDB HTTP/HTTPS 地址')
 if body.mode not in ('rules','manual'):raise HTTPException(422,'未知下载方式')
 if body.mode=='manual' and (not body.downloader.strip() or not body.save_path.strip()):raise HTTPException(422,'请填写默认下载器和保存路径')
 if not data['api_key']:data['api_key']=connection_settings()['api_key']
 settings_file.parent.mkdir(parents=True,exist_ok=True)
 temporary=settings_file.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temporary.replace(settings_file)
 return {'ok':True}

class Search(BaseModel):
 keyword: str = Field(default='', max_length=500)
 website: str = ''
 section: str = ''
 category: str = ''
 page: int = Field(default=1, ge=1)
 page_size: int = Field(default=20, ge=1, le=100)

@router.get('/status')
def status():
 with session_scope() as db:
  readonly=db.execute(text('SHOW transaction_read_only')).scalar()=='on'
 return {'configured': bool(os.getenv('AVDB_URL') and os.getenv('AVDB_API_KEY')),'database_connected':True,'database_readonly':readonly}

@router.get('/filters')
def filters():
 with session_scope() as db:
  rows=db.query(Target.website,Target.section,Target.category).distinct().all()
  return [dict(website=w or '',section=s or '',category=c or '') for w,s,c in rows]

@router.post('/search')
def search(body:Search):
 terms=list(dict.fromkeys(body.keyword.split()))
 if len(terms)>20:raise HTTPException(422,'最多输入 20 个关键词')
 with session_scope() as db:
  q=db.query(Target)
  for term in terms:
   escaped=term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
   q=q.filter(Target.title.ilike('%'+escaped+'%',escape='\\'))
  for key in ('website','section','category'):
   if getattr(body,key):q=q.filter(getattr(Target,key)==getattr(body,key))
  total=q.count()
  rows=q.order_by(Target.publish_date.desc().nullslast(),Target.tid.desc()).offset((body.page-1)*body.page_size).limit(body.page_size).all()
  return {'total':total,'items':[dict(tid=r.tid,title=r.title,website=r.website,section=r.section,category=r.category,size=r.size,publish_date=r.publish_date,preview_images=links(r.preview_images),detail_url=r.detail_url) for r in rows]}

class Download(BaseModel):
 tids:list[int]=Field(min_length=1,max_length=100)
 mode:str='rules'
 downloader:str=''
 save_path:str=''
 use_defaults:bool=False

def execute_download(body:Download,record_id):
 cfg=connection_settings()
 url=cfg['url'].rstrip('/')
 key=cfg['api_key']
 if body.use_defaults:
  body.mode=cfg['mode'];body.downloader=cfg['downloader'];body.save_path=cfg['save_path']
 if not url or not key:raise HTTPException(503,'尚未配置 AVDB_URL 和 AVDB_API_KEY')
 if body.mode not in ('rules','manual'):raise HTTPException(422,'未知下载方式')
 if body.mode=='manual' and (not body.downloader.strip() or not body.save_path.strip()):raise HTTPException(422,'请填写下载器标识和保存路径')
 tids=list(dict.fromkeys(body.tids))
 with session_scope() as db:
  if db.query(Target).filter(Target.tid.in_(tids)).count()!=len(tids):raise HTTPException(422,'部分资源已不存在，请重新搜索')
 path='/api/v1/articles/download'
 params={'tid':tids[0]} if len(tids)==1 else {'tids':','.join(map(str,tids))}
 if body.mode=='manual':path+='/manul';params.update(downloader=body.downloader.strip(),save_path=body.save_path.strip())
 if len(tids)>1:path+='/batch'
 update_push(record_id,'sending','正在提交至 AVDB')
 try:
  response=requests.get(url+path,params=params,headers={'X-API-Key':key},timeout=(5,60))
 except requests.RequestException:
  raise HTTPException(502,'AVDB 请求未得到确认，请到 AVDB 检查任务后再决定是否重试')
 if not response.ok:raise HTTPException(502,f'AVDB 返回 HTTP {response.status_code}，请检查密钥权限或下载配置')
 try:result=response.json()
 except ValueError:raise HTTPException(502,'AVDB 响应格式异常，请到 AVDB 检查任务')
 if isinstance(result,dict) and result.get('code',0)!=0:raise HTTPException(422,str(result.get('message') or result.get('msg') or 'AVDB 未接受任务'))
 return {'message':'请求已提交至 AVDB，请在 AVDB 查看处理结果','result':result}


log_file=Path(data_path)/'push-records.sqlite3'
@contextmanager
def log_db():
 log_file.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(log_file,timeout=10)
 db.row_factory=sqlite3.Row
 db.execute('CREATE TABLE IF NOT EXISTS push_records (id INTEGER PRIMARY KEY, created_at TEXT, finished_at TEXT, tids TEXT, mode TEXT, downloader TEXT, save_path TEXT, quick INTEGER, status TEXT, message TEXT)')
 try:
  with db:yield db
 finally:db.close()

def update_push(record_id,status,message):
 with log_db() as db:
  db.execute('UPDATE push_records SET status=?,message=?,finished_at=? WHERE id=?',(status,message,datetime.now(timezone.utc).isoformat(),record_id))

@router.get('/push-records')
def push_records(page:int=Query(default=1,ge=1),status:str=''):
 where=' WHERE status=?' if status else ''
 args=[status] if status else []
 with log_db() as db:
  total=db.execute('SELECT count(*) FROM push_records'+where,args).fetchone()[0]
  rows=db.execute('SELECT * FROM push_records'+where+' ORDER BY id DESC LIMIT 20 OFFSET ?',args+[(page-1)*20]).fetchall()
 return {'total':total,'items':[{**dict(r),'tids':json.loads(r['tids'])} for r in rows]}

@router.post('/download')
def download(body:Download):
 cfg=connection_settings()
 if body.use_defaults:
  body.mode=cfg['mode'];body.downloader=cfg['downloader'];body.save_path=cfg['save_path']
 with log_db() as db:
  cursor=db.execute('INSERT INTO push_records (created_at,tids,mode,downloader,save_path,quick,status,message) VALUES (?,?,?,?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),json.dumps(list(dict.fromkeys(body.tids))),body.mode,body.downloader if body.mode=='manual' else '',body.save_path if body.mode=='manual' else '',int(body.use_defaults),'pending','正在检查资源与配置'))
  record_id=cursor.lastrowid
 try:
  result=execute_download(body,record_id)
 except HTTPException as exc:
  uncertain=exc.status_code==502 and ('未得到确认' in str(exc.detail) or '响应格式异常' in str(exc.detail) or 'HTTP 5' in str(exc.detail))
  update_push(record_id,'unknown' if uncertain else 'failed',str(exc.detail))
  raise
 except Exception:
  update_push(record_id,'failed','推送处理异常，请检查本机服务与数据库连接')
  raise
 update_push(record_id,'submitted',result['message'])
 return result
