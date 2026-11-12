import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from loguru import logger
from app.core.database import session_scope
from app.models import Article,Batch,TaskLog
sync_pool=ThreadPoolExecutor(max_workers=1)
pool=ThreadPoolExecutor(max_workers=1)
stop=threading.Event();local=threading.local();active=None;lock=threading.Lock()
sync_pending=0;phase='idle'
def sync_batch(filters,bid):
 global sync_pending
 local.batch_id=bid
 try:
  from app.collector.sync import process
  return process(filters,wait=True)
 except Exception:
  logger.exception('实时同步异常，待同步文章将由收尾或兜底任务补处理')
  raise
 finally:
  local.batch_id=None
  with lock:sync_pending-=1
def enqueue_sync(filters,bid):
 global sync_pending
 with lock:sync_pending+=1
 try:return sync_pool.submit(sync_batch,filters,bid)
 except Exception:
  with lock:sync_pending-=1
  raise
class Stopped(BaseException):pass
def check_stop():
 if stop.is_set():raise Stopped()
def current_batch():return getattr(local,'batch_id',None)
def record_items(tids):
 ids=[]
 with session_scope() as db:
  for article in db.query(Article).filter(Article.website=='sehuatang',Article.tid.in_(tids)).all():
   ids.append(article.id)

 from app.collector.sync import settings
 if ids and settings()['mode']=='realtime':enqueue_sync({'ids':ids,'merge_status':'pending'},current_batch())
def log_sink(message):
 if message.record['extra'].get('retry_detail'):return
 batch=current_batch()
 if getattr(local,'logging',False):return
 if batch:
  try:
   local.logging=True
   with session_scope() as db:db.add(TaskLog(batch_id=batch,message=str(message).strip()))
  except Exception:pass
  finally:local.logging=False
logger.add(log_sink)
def launch(params,name='色花堂采集',trigger='manual'):
 global active,phase
 with lock:
  if active is not None:raise ValueError('已有采集任务运行，请先停止或等待完成')
  with session_scope() as db:
   b=Batch(kind='crawl',details={'name':name,'trigger':trigger,'params':params,'sections':{}});db.add(b);db.flush();bid=b.id
  active=bid;phase='crawling';stop.clear();pool.submit(run,bid,params);return bid
def run(bid,params):
 global active,phase
 local.batch_id=bid;status='completed'
 try:
  from app.collector.recovery import replay
  replay()
  from app.scheduler.sht_sheduler import sync_sht
  result=sync_sht(**params)
  check_stop()
  from app.collector.sync import settings
  if settings()['mode']=='realtime':
   with lock:phase='syncing'
   logger.info('采集完成，等待实时同步队列并检查本批次待同步文章')
   enqueue_sync({'batch_id':bid,'merge_status':'pending'},bid).result()
   with session_scope() as db:
    remaining=db.query(Article).filter_by(batch_id=bid,merge_status='pending').count()
   if remaining:raise RuntimeError(f'本批次仍有 {remaining} 条待同步，请查看日志并重试')
   merged='本批次同步结束，失败及冲突项保留待手动处理'
   logger.success(merged)
  else:merged='等待定时或兜底同步'
  message=f'采集结果：{result}；合并：{merged}'
 except Stopped:status='stopped';message='用户停止，已保存的数据留在暂存表，未自动合并'
 except Exception as e:
  status='failed';message=f'{type(e).__name__}: {e}'
  logger.exception('采集任务中断，已保存的恢复缓冲将在数据库恢复后重放')
 finally:
  try:
   with session_scope() as db:
    b=db.get(Batch,bid);b.status=status;b.message=message;b.finished_at=datetime.now(timezone.utc)
    if status in ('stopped','failed'):
     details=dict(b.details or {});parts={k:dict(v) for k,v in details.get('sections',{}).items()}
     for part in parts.values():
      if part.get('reason')=='正在采集':part['reason']='用户停止' if status=='stopped' else '任务异常中断'
     details['sections']=parts;b.details=details
  except Exception:logger.exception('任务结果保存失败，已保留本地缓冲')
  finally:
   local.batch_id=None
   with lock:active=None;phase='idle'
