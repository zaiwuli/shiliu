import io,json,hashlib,os
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
from fastapi import FastAPI,HTTPException,UploadFile,File
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text,func
from app.core.database import Base,engine,session_scope
from app.core.config import config_manager
from app.models import Article,Task,Batch,TaskLog,Config,Converted,Target,Retry
from app.collector import sync
from app.collector import service,runtime
from app.scheduler.sht_sheduler import section_map
scheduler=BackgroundScheduler()
def schedule():
 scheduler.remove_all_jobs()
 from app.collector.retry import tick
 scheduler.add_job(tick,'interval',seconds=60,id='retry-worker',max_instances=1)
 cfg=sync.settings()
 scheduler.add_job(sync.fallback,"interval",minutes=cfg["fallback_minutes"],id="sync-fallback",max_instances=1)
 if cfg["mode"]=="scheduled":scheduler.add_job(sync.process,CronTrigger.from_crontab(cfg["cron"]),id="sync-scheduled",max_instances=1)
 with session_scope() as db:
  for t in db.query(Task).filter(Task.enabled==True).all():
   if t.cron:scheduler.add_job(runtime.launch,CronTrigger.from_crontab(t.cron),args=[t.params,t.name,'scheduled'],id=str(t.id),max_instances=1)
@asynccontextmanager
async def lifespan(app):
 from sqlalchemy import inspect
 inspector=inspect(engine)
 if not inspector.has_table('article'):
  raise RuntimeError('未找到 Avdb article 表，请连接已初始化的 Avdb 数据库')
 required={c.name for c in Target.__table__.columns}
 missing=required-{c['name'] for c in inspector.get_columns('article')}
 if missing:raise RuntimeError('Avdb article 表缺少字段：'+', '.join(sorted(missing)))
 from app.core.schema import initialize_collector_tables
 initialize_collector_tables(engine,Base.metadata)
 with session_scope() as db:
  config=db.get(Config,'network')
  if config:config_manager.reload(config.content)
  for batch in db.query(Batch).filter(Batch.status=='running').all():batch.status='interrupted';batch.message='服务重启中断，已保存的数据可手动合并'
  for row in db.query(Retry).filter(Retry.status=='running'):row.status=row.resume_status or ('manual' if row.auto_attempts>=3 else 'waiting')
 schedule();scheduler.start();yield
 runtime.stop.set();scheduler.shutdown(wait=False)
app=FastAPI(title='拾流',lifespan=lifespan)
@app.get('/api/retries')
def retries(status:str='waiting',page:int=1):
 with session_scope() as db:
  q=db.query(Retry)
  if status:q=q.filter(Retry.status==status)
  return {'total':q.count(),'items':[service.serialize(r) for r in q.order_by(Retry.id.desc()).offset((max(page,1)-1)*50).limit(50)]}
@app.get('/api/retries/{rid}/links')
def retry_links(rid:int):
 with session_scope() as db:
  row=db.get(Retry,rid)
  if not row:raise HTTPException(404,'补抓记录不存在')
  article=db.query(Article).filter_by(website=row.website,tid=row.tid).first()
  return {'tid':row.tid,'detail_url':article.detail_url if article else f'https://sehuatang.org/thread-{row.tid}-1-2.html','title':article.title if article else None,'magnet':article.magnet if article else [],'edk':article.edk if article else []}
class RetryAction(BaseModel):
 action:str
 ids:list[int]|None=None
 status:str|None=None
@app.post('/api/retries/action')
def retry_action(body:RetryAction):
 from app.collector.retry import launch
 if body.action not in ('run','ignore','delete','restart'):raise HTTPException(422,'未知操作')
 if not body.ids and not body.status:raise HTTPException(422,'请选择记录或筛选状态')
 with runtime.lock:
  with session_scope() as db:
   q=db.query(Retry).filter(Retry.status!='running')
   if body.ids:q=q.filter(Retry.id.in_(body.ids))
   else:q=q.filter(Retry.status==body.status)
   rows=q.all();ids=[r.id for r in rows]
   if body.action=='run':
    if runtime.active is not None:raise HTTPException(409,'采集或补抓正在运行，请稍后重试')
    if any(r.status not in ('waiting','manual') for r in rows):raise HTTPException(422,'请先重新启用已忽略记录')
   else:
    for r in rows:
     if body.action=='delete':db.delete(r)
     elif body.action=='ignore':r.status='ignored';r.next_run=None
     else:r.status='waiting';r.auto_attempts=0;r.next_run=datetime.now(timezone.utc)
 if body.action=='run':
  if not ids:raise HTTPException(422,'没有可补抓记录')
  if not launch(ids):raise HTTPException(409,'执行器忙碌，请重试')
 return {'count':len(ids),'message':'补抓任务已开始' if body.action=='run' else '操作完成'}
class Filters(BaseModel):
 website:str|None=None;section:str|None=None;source:str|None=None;batch_id:int|None=None;merge_status:str|None=None;keyword:str|None=None;ids:list[int]|None=None;sections:list[str]|None=None;keep_section:str|None=None;min_tid:int|None=None;max_tid:int|None=None
class Plan(BaseModel):
 name:str=Field(min_length=1);section_id_list:list[str]=Field(min_length=1);start_page:int=Field(default=1,ge=1);max_page:int|None=Field(default=None,ge=1);stop_after_empty_pages:int=Field(default=3,ge=1,le=100);cron:str|None=None;enabled:bool=False
 def params(self):
  if any(x not in section_map for x in self.section_id_list):raise HTTPException(422,'未知板块')
  if self.max_page and self.max_page<self.start_page:raise HTTPException(422,'结束页不能小于起始页')
  return self.model_dump(include={'section_id_list','start_page','max_page','stop_after_empty_pages'})
@app.get('/api/overview')
def overview():
 with session_scope() as db:
  return dict(total=db.query(Article).count(),pending=db.query(Article).filter(Article.merge_status=='pending').count(),active=runtime.active,phase=runtime.phase,sync_queued=runtime.sync_pending,sections=section_map,groups=[dict(section=s,source=o,count=c) for s,o,c in db.query(Article.section,Article.source,func.count()).group_by(Article.section,Article.source)],batches=[service.serialize(b) for b in db.query(Batch).filter(Batch.kind!='sync').order_by(Batch.id.desc()).limit(30)])
@app.post('/api/articles/search')
def articles(f:Filters,page:int=1):
 with session_scope() as db:
  q=service.filtered(db,f.model_dump());return {'total':q.count(),'items':[service.serialize(a) for a in q.order_by(Article.id.desc()).offset((max(1,page)-1)*30).limit(30)]}
@app.post('/api/convert')
def preview(f:Filters):
 with session_scope() as db:
  out=[]
  for a in service.filtered(db,f.model_dump()).limit(10):
   try:out.append({'id':a.id,'target':service.convert(a)})
   except Exception as e:out.append({'id':a.id,'error':str(e)})
  return out
@app.post('/api/merge')
def merge(f:Filters):
 if runtime.active:raise HTTPException(409,'采集中请等待结束')
 return sync.start(f.model_dump())
@app.get('/api/sync/status')
def sync_status():return sync.state()
class Resolution(BaseModel):
 filters:Filters
 operation:str
 confirmation:str|None=None
def resolution_preview(body,db):
 if body.operation not in ('clear_size','resolve_conflict'):raise HTTPException(422,'未知处理方式')
 rows=service.filtered(db,body.filters.model_dump()).order_by(Article.id).all()
 items=[]
 for a in rows:
  if body.operation=='clear_size' and (a.merge_status!='failed' or a.error!='大小超出目标整数范围'):continue
  if body.operation=='resolve_conflict' and a.merge_status!='conflict':continue
  tid=a.tid*10001 if body.operation=='resolve_conflict' else a.tid
  target=db.get(Target,tid)
  mapping=db.query(Converted).filter(Converted.target_tid==tid,Converted.article_id!=a.id).first()
  occupied=bool(target or mapping) if body.operation=='resolve_conflict' else False
  original=db.get(Target,a.tid)
  items.append(dict(id=a.id,tid=a.tid,title=a.title,size=a.size,target_tid=tid,available=not occupied and 0<tid<=9007199254740991,existing_title=original.title if original else None,existing_website=original.website if original else None))
 token=hashlib.sha256(json.dumps([body.operation,items],sort_keys=True,default=str).encode()).hexdigest()
 return dict(items=items,confirmation=token)
@app.post('/api/resolve/preview')
def resolve_preview(body:Resolution):
 with session_scope() as db:return resolution_preview(body,db)
@app.post('/api/resolve')
def resolve(body:Resolution):
 if runtime.active:raise HTTPException(409,'采集中请等待结束')
 with session_scope() as db:preview=resolution_preview(body,db)
 if body.confirmation!=preview['confirmation']:raise HTTPException(409,'数据已变化，请重新预览确认')
 ids=[item['id'] for item in preview['items'] if item['available']]
 if not ids:raise HTTPException(422,'没有可以处理的记录')
 return sync.start({'ids':ids},body.operation)
@app.post('/api/import/file')
async def upload(file:UploadFile=File(...)):
 data=await file.read(50*1024*1024+1)
 if len(data)>50*1024*1024:raise HTTPException(413,'文件上限 50 MiB')
 name=(file.filename or '').lower()
 try:
  if name.endswith('.csv'):
   try:df=pd.read_csv(io.BytesIO(data),dtype={'tid':str})
   except UnicodeDecodeError:df=pd.read_csv(io.BytesIO(data),encoding='gb18030',dtype={'tid':str})
  else:raise ValueError('仅支持 CSV')
  rows=df.astype(object).where(pd.notnull(df),None).to_dict('records');return service.ingest(rows,'file')
 except Exception as e:raise HTTPException(422,str(e))
@app.post('/api/export')
def export(f:Filters,format:str="csv"):
 with session_scope() as db:
  rows=[service.serialize(a) for a in service.filtered(db,f.model_dump())]
 for row in rows:
  for k in ['magnet','edk','preview_images']:row[k]=json.dumps(row[k] or [],ensure_ascii=False)
 if format=='xlsx':
  for row in rows:
   for key in ['create_time','update_time','merged_at']:
    if row.get(key):row[key]=row[key].isoformat()
  stream=io.BytesIO();pd.DataFrame(rows).to_excel(stream,index=False,engine='openpyxl')
  return StreamingResponse(iter([stream.getvalue()]),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=shiliu-articles.xlsx'})
 return StreamingResponse(iter([pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=shiliu-articles.csv'})
def deletion(f,db):
 if not f.sections:raise HTTPException(422,'请至少选择一个板块')
 return db.query(Article).filter(Article.section.in_(f.sections)).order_by(Article.id).all()
@app.post('/api/cleanup/preview')
def cleanup_preview(f:Filters):
 with session_scope() as db:
  rows=deletion(f,db);ids=[a.id for a in rows];return {'count':len(ids),'confirmation':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),'sections':sorted(set(a.section for a in rows))}
class Cleanup(BaseModel):
 filters:Filters;confirmation:str
@app.post('/api/cleanup')
def cleanup(body:Cleanup):
 if runtime.active or sync.lock.locked():raise HTTPException(409,'采集或同步运行中不能清理，请稍后重试')
 with session_scope() as db:
  rows=deletion(body.filters,db);ids=[a.id for a in rows]
  if hashlib.sha256(json.dumps(ids).encode()).hexdigest()!=body.confirmation:raise HTTPException(409,'范围已变化，请重新预览')
  db.query(Converted).filter(Converted.article_id.in_(ids)).delete(synchronize_session=False)
  for a in rows:db.delete(a)
  db.add(Batch(kind='cleanup',status='completed',message=f'清理暂存数据 {len(ids)} 条；不删除目标表',finished_at=datetime.now(timezone.utc)))
  return {'deleted':len(ids)}
@app.get('/api/tasks')
def tasks():
 with session_scope() as db:return [service.serialize(t) for t in db.query(Task).order_by(Task.id)]
@app.post('/api/tasks')
def save_task(p:Plan):
 params=p.params()
 if p.cron:
  try:CronTrigger.from_crontab(p.cron)
  except Exception:raise HTTPException(422,'Cron 格式错误')
 with session_scope() as db:db.add(Task(name=p.name,params=params,cron=p.cron,enabled=p.enabled))
 schedule();return {'ok':True}
@app.put('/api/tasks/{tid}')
def edit_task(tid:int,p:Plan):
 params=p.params()
 if p.cron:
  try:CronTrigger.from_crontab(p.cron)
  except Exception:raise HTTPException(422,'Cron 格式错误')
 with session_scope() as db:
  task=db.get(Task,tid)
  if not task:raise HTTPException(404,'计划不存在')
  task.name=p.name;task.params=params;task.cron=p.cron;task.enabled=p.enabled
 schedule();return {'ok':True}
@app.delete('/api/tasks/{tid}')
def delete_task(tid:int):
 with session_scope() as db:
  t=db.get(Task,tid)
  if t:db.delete(t)
 schedule();return {'ok':True}
@app.post('/api/tasks/run')
def run(p:Plan):
 try:return {'batch_id':runtime.launch(p.params(),p.name,'manual')}
 except ValueError as e:raise HTTPException(409,str(e))
@app.post('/api/tasks/stop')
def stop():runtime.stop.set();return {'message':'将在当前请求或步骤结束后停止'}
@app.get('/api/logs/{bid}')
def logs(bid:int):
 with session_scope() as db:return [service.serialize(l) for l in db.query(TaskLog).filter_by(batch_id=bid).order_by(TaskLog.id.desc()).limit(300)]
@app.get('/api/sync/history')
def sync_history():
 with session_scope() as db:
  rows=[];now=datetime.now(timezone.utc)
  for b in db.query(Batch).filter(Batch.kind=='sync').order_by(Batch.id.desc()).limit(101):
   try:summary=json.loads(b.message or '{}')
   except ValueError:summary={}
   window=summary.get('window')
   if window:
    end=datetime.fromisoformat(window)+timedelta(minutes=5)
    if now<end:continue
    row=service.serialize(b);row['create_time']=end;rows.append(row)
   else:rows.append(service.serialize(b))
   if len(rows)>=100:break
  return rows
@app.get('/api/ledger')
def ledger_list(page:int=1,page_size:int=10,trigger:str=''):
 from app.collector.ledger import listing
 if page_size not in (5,10,20):raise HTTPException(422,'每页条数应为 5、10 或 20')
 if trigger not in ('','manual','scheduled','import'):raise HTTPException(422,'未知任务类型')
 return listing(page,page_size,trigger)
@app.get('/api/ledger/{bid}')
def ledger_detail(bid:int):
 from app.collector.ledger import detail
 result=detail(bid)
 if result is None:raise HTTPException(404,'采集或导入任务不存在')
 return result
@app.get('/api/runtime-logs')
def runtime_logs():
 from app.utils.log import read_console_logs
 return read_console_logs()
@app.get('/api/settings')
def settings():
 cfg=config_manager.get();return {'PROXY':cfg.PROXY or '','FLARE_SOLVERR_URL':cfg.FLARE_SOLVERR_URL or '','database':engine.url.render_as_string(hide_password=True),'target':'article（Avdb 主表）'}
class Network(BaseModel):
 PROXY:str='';FLARE_SOLVERR_URL:str=''
@app.post('/api/settings')
def settings_save(n:Network):
 payload=n.model_dump()
 with session_scope() as db:
  c=db.get(Config,'network')
  if c:c.content=payload
  else:db.add(Config(key='network',content=payload))
 config_manager.reload(payload);return {'ok':True}
@app.get('/api/health')
def health():
 with engine.connect() as conn:conn.execute(text('select 1'))
 return {'database':True,'target':'article','authentication':'none'}
dist=Path('/frontend/dist') if os.environ.get('DOCKER_ENV') else Path(__file__).resolve().parents[2]/'frontend/dist'


class SyncSettings(BaseModel):
 mode:str='realtime'
 cron:str='0 * * * *'
 fallback_minutes:int=Field(default=15,ge=1,le=1440)
@app.get('/api/sync/settings')
def sync_settings():return sync.settings()
@app.post('/api/sync/settings')
def sync_settings_save(payload:SyncSettings):
 if payload.mode not in ('realtime','scheduled'):raise HTTPException(422,'未知同步方式')
 try:CronTrigger.from_crontab(payload.cron)
 except Exception:raise HTTPException(422,'Cron 格式错误')
 with session_scope() as db:
  row=db.get(Config,'sync')
  if row:row.content=payload.model_dump()
  else:db.add(Config(key='sync',content=payload.model_dump()))
 schedule();return payload.model_dump()

if dist.exists():app.mount('/',StaticFiles(directory=str(dist),html=True),name='frontend')
