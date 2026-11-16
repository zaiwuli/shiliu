"""Search the external AVDB table and submit downloads through its API."""
import os,json,csv,sqlite3,socket,ipaddress,threading
from datetime import datetime,timezone
from fastapi import Query,Response
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
 data={'url':os.getenv('AVDB_URL',''),'api_key':os.getenv('AVDB_API_KEY',''),'mode':'rules','downloader':'','save_path':'','username':'','password':''}
 if settings_file.exists():data.update(json.loads(settings_file.read_text(encoding='utf-8')))
 return data
class ConnectionSettings(BaseModel):
 url:str
 api_key:str=''
 mode:str='rules'
 downloader:str=''
 save_path:str=''
 username:str=''
 password:str=''
@router.get('/settings')
def get_settings():
 data=connection_settings()
 return {k:v for k,v in {**data,'api_key':'','password':'','key_configured':bool(data['api_key']),'password_configured':bool(data.get('password')),'authenticated':bool(auth_session.get('token'))}.items() if k not in ('mode','downloader','save_path')}
@router.post('/settings')
def save_settings(body:ConnectionSettings):
 data=body.model_dump();data['url']=body.url.strip().rstrip('/')
 parsed=urlparse(data['url'])
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise HTTPException(422,'请输入有效的 AVDB HTTP/HTTPS 地址')
 data['mode']='rules';data['downloader']='';data['save_path']=''
 old=connection_settings()
 if not data['api_key']:data['api_key']=old['api_key']
 if not data['password'] and data['url']==old['url'] and data['username']==old.get('username',''):data['password']=old.get('password','')
 if any(data.get(k)!=old.get(k) for k in ('url','username','password')):auth_session.clear()
 settings_file.parent.mkdir(parents=True,exist_ok=True)
 temporary=settings_file.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temporary.replace(settings_file)
 return {'ok':True}

# Login credentials stay on the server; JWT and pending OTP are kept in memory only.
auth_session={}
auth_lock=threading.RLock()
class LoginVerification(BaseModel):
 otp_code:str=''
 recovery_code:str=''

def login_avdb(verification=None):
 cfg=connection_settings()
 if not cfg.get('url') or not cfg.get('password'):raise HTTPException(401,'请先保存 AVDB 登录账号和密码，再验证连接')
 with auth_lock:
  pending=auth_session.get('otp_token')
  second=bool(verification and (verification.otp_code or verification.recovery_code))
  if second and not pending:raise HTTPException(401,'验证会话已失效，请重新验证连接')
  form={'otp_token':pending,'otp_code':verification.otp_code,'recovery_code':verification.recovery_code} if second else {'username':cfg.get('username',''),'password':cfg['password']}
  try:
   response=requests.post(cfg['url'].rstrip('/')+'/api/v1/users/login'+('/2fa' if second else ''),data=form,timeout=(5,20),allow_redirects=False)
   result=response.json()
  except (requests.RequestException,ValueError):raise HTTPException(502,'无法完成 AVDB 登录，请检查地址与网络')
  if not response.ok or not isinstance(result,dict) or result.get('code',0)!=0:
   raise HTTPException(401,'AVDB 登录验证失败，请检查账号、密码或验证码')
  payload=result.get('data') or result
  if payload.get('access_token'):
   auth_session.clear();auth_session['token']=payload['access_token']
   return {'authenticated':True,'requires_2fa':False}
  if payload.get('otp_token'):
   auth_session.clear();auth_session['otp_token']=payload['otp_token']
   return {'authenticated':False,'requires_2fa':True}
  raise HTTPException(502,'AVDB 登录响应缺少凭证，请检查版本')

@router.post('/auth/verify')
def verify_login(body:LoginVerification):
 return login_avdb(body)

def download_auth():
 with auth_lock:
  if not auth_session.get('token'):
   result=login_avdb()
   if result['requires_2fa']:raise HTTPException(401,'请在连接与推送设置中完成 AVDB 两步验证')
  return {'Authorization':'Bearer '+auth_session['token']}

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

def image_proxy_settings():
 local=Path(data_path)/'network-settings.json'
 if local.exists():return str(json.loads(local.read_text(encoding='utf-8')).get('PROXY') or '').strip()
 return str(config_manager.get().PROXY or '').strip()

def public_image_url(url):
 parsed=urlparse(url)
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise HTTPException(422,'图片地址无效')
 try:
  addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
 except OSError:raise HTTPException(502,'无法解析图片服务器')
 if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):raise HTTPException(422,'仅支持公网图床图片')
 return parsed

@router.get('/images/{tid}/{position}')
def image(tid:int,position:int):
 with session_scope() as db:
  row=db.query(Target).filter(Target.tid==tid).first()
  images=links(row.preview_images) if row else []
  if position<0 or position>=len(images):raise HTTPException(404,'图片不存在')
  url=images[position]
  detail=row.detail_url or ''
 proxy=image_proxy_settings()
 proxies={'http':proxy,'https':proxy} if proxy else {}
 with requests.Session() as client:
  client.trust_env=False
  headers={'User-Agent':'Mozilla/5.0','Accept':'image/avif,image/webp,image/*,*/*;q=0.8'}
  source=urlparse(detail)
  if source.scheme in ('http','https') and source.netloc:headers['Referer']=f'{source.scheme}://{source.netloc}/'
  for _ in range(5):
   public_image_url(url)
   try:
    with client.get(url,proxies=proxies,headers=headers,timeout=(5,20),stream=True,allow_redirects=False) as remote:
     if remote.status_code in (301,302,303,307,308):
      from urllib.parse import urljoin
      url=urljoin(url,remote.headers.get('Location',''));continue
     if not remote.ok:raise HTTPException(502,f'图床返回 HTTP {remote.status_code}')
     mime=remote.headers.get('Content-Type','').split(';')[0].lower()
     if mime not in ('image/jpeg','image/png','image/gif','image/webp','image/avif','image/bmp'):raise HTTPException(502,'图床未返回支持的图片')
     chunks=[];size=0
     for chunk in remote.iter_content(65536):
      size+=len(chunk)
      if size>20*1024*1024:raise HTTPException(413,'图片超过 20MB')
      chunks.append(chunk)
     return Response(b''.join(chunks),media_type=mime,headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})
   except requests.RequestException:raise HTTPException(502,'图片获取失败，请检查代理和图床连接')
 raise HTTPException(502,'图片重定向次数过多')

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
  return {'total':total,'items':[dict(tid=r.tid,title=r.title,website=r.website,section=r.section,category=r.category,size=r.size,publish_date=r.publish_date,preview_images=[f'/api/avdb/images/{r.tid}/{i}' for i in range(len(links(r.preview_images)))],detail_url=r.detail_url) for r in rows]}

class Download(BaseModel):
 tids:list[int]=Field(min_length=1,max_length=100)
 mode:str='rules'
 downloader:str=''
 save_path:str=''
 use_defaults:bool=False

def execute_download(body:Download,record_id):
 cfg=connection_settings()
 url=cfg['url'].rstrip('/')
 if not url:raise HTTPException(503,'尚未配置 AVDB 地址')
 headers=download_auth()
 tids=list(dict.fromkeys(body.tids))
 with session_scope() as db:
  if db.query(Target).filter(Target.tid.in_(tids)).count()!=len(tids):raise HTTPException(422,'部分资源已不存在，请重新搜索')
 path='/api/v1/articles/download'
 params={'tid':tids[0]} if len(tids)==1 else {'tids':','.join(map(str,tids))}
 if len(tids)>1:path+='/batch'
 update_push(record_id,'sending','正在提交至 AVDB')
 try:
  response=requests.get(url+path,params=params,headers=headers,timeout=(5,60),allow_redirects=False)
 except requests.RequestException:
  raise HTTPException(502,'AVDB 请求未得到确认，请到 AVDB 检查任务后再决定是否重试')
 if response.status_code==401:
  auth_session.clear()
  raise HTTPException(401,'AVDB 登录已失效，请在连接与推送设置中重新验证；本次未自动重发')
 if not response.ok:raise HTTPException(502,f'AVDB 返回 HTTP {response.status_code}，请检查 AVDB 下载规则或服务状态')
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
def push_records(page:int=Query(default=1,ge=1),status:str='',page_size:int=Query(default=10,ge=1,le=20)):
 where=' WHERE status=?' if status else ''
 args=[status] if status else []
 with log_db() as db:
  total=db.execute('SELECT count(*) FROM push_records'+where,args).fetchone()[0]
  rows=db.execute('SELECT * FROM push_records'+where+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[page_size,(page-1)*page_size]).fetchall()
 return {'total':total,'items':[{**dict(r),'tids':json.loads(r['tids'])} for r in rows]}

@router.post('/download')
def download(body:Download):
 cfg=connection_settings()
 body.mode='rules';body.downloader='';body.save_path=''
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
