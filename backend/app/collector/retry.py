"""Automatic extra retries, serialized with ordinary crawling."""
from datetime import datetime,timedelta,timezone
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_scope
from app.models import Retry,Article,Batch
from app.collector import runtime
from app.utils.log import logger

def register(website,section,tids,source_batch_id=None):
 with session_scope() as db:
  for tid in set(tids):
   db.execute(insert(Retry).values(website=website,tid=tid,section=section,source_batch_id=source_batch_id,status='waiting',auto_attempts=0,manual_attempts=0,error='详情或附件未获得可用资源',next_run=datetime.now(timezone.utc)+timedelta(minutes=5)).on_conflict_do_nothing(index_elements=['website','tid']))

def launch(ids=None):
 with runtime.lock:
  if runtime.active is not None:return False
  with session_scope() as db:
   query=db.query(Retry).filter(Retry.status.in_(['waiting','manual'])).order_by(Retry.id)
   if ids is not None:query=query.filter(Retry.id.in_(ids))
   else:
    now=datetime.now(timezone.utc)
    group_due=func.max(Retry.next_run)
    source=(db.query(Retry.source_batch_id)
            .filter(Retry.status=='waiting',Retry.source_batch_id.is_not(None))
            .group_by(Retry.source_batch_id).having(group_due<=now)
            .order_by(group_due,Retry.source_batch_id).first())
    query=query.filter(Retry.status=='waiting')
    if source is not None:query=query.filter(Retry.source_batch_id==source[0])
    else:query=query.filter(Retry.source_batch_id.is_(None),Retry.next_run<=now).limit(50)
   rows=query.all()
   if not rows:return False
   sources={r.source_batch_id for r in rows}
   source_label='、'.join(f'采集任务 #{i}' for i in sorted(sources-{None}))
   if None in sources:source_label+='、历史补抓记录' if source_label else '历史补抓记录'
   bid=Batch(kind='retry',status='running',message=f'{source_label}：补抓中',details={'source_batches':sorted(sources-{None}),'manual':ids is not None,'total':len(rows)});db.add(bid);db.flush();batch_id=bid.id
   selected=[r.id for r in rows]
   for r in rows:r.resume_status=r.status;r.status='running'
  runtime.active=batch_id;runtime.phase='retrying';runtime.stop.clear()
  runtime.pool.submit(run,batch_id,selected,ids is not None,source_label)
 return True

def tick():
 if runtime.active is not None:return
 from app.collector.recovery import replay
 replay()
 launch()

def run(bid,ids,manual,source_label):
 runtime.local.batch_id=bid;completed=False
 stats={'recovered':0,'waiting':0,'manual':0};processed=0
 try:
  from app.modules.crawler.sht import sht
  from app.scheduler.crawler_scheduler import save_articles,_extract_article_match_number
  from app.collector.recovery import replay
  replay();sht.mode='direct'
  for rid in ids:
   runtime.check_stop()
   with session_scope() as db:
    r=db.get(Retry,rid);tid=r.tid;section=r.section;website=r.website;origin=r.source_batch_id
    exists=db.query(Article).filter_by(tid=tid,website=website).first() is not None
   error=None
   try:
    with logger.contextualize(retry_detail=True):
     data=None if exists else sht.crawler_detail(tid, expanded_links=True)
   except Exception as e:data=None;error=f'{type(e).__name__}: {e}'
   if data:
    data.update(tid=tid,section=section,website=website,origin_batch_id=origin,match_number=_extract_article_match_number(data.get('title')))
    save_articles([Article(**data)])
   with session_scope() as db:
    r=db.get(Retry,rid)
    if manual:r.manual_attempts+=1
    else:r.auto_attempts+=1
    if exists or data:r.status='recovered';r.error=None;r.next_run=None
    else:
     r.error=error or '详情或附件未获得可用资源'
     r.status='manual' if manual or r.auto_attempts>=3 else 'waiting'
     r.next_run=None if r.status=='manual' else datetime.now(timezone.utc)+timedelta(minutes=30 if r.auto_attempts==1 else 120)
    result_status=r.status
   stats[result_status]+=1;processed+=1
   if runtime.stop.wait(1):runtime.check_stop()
  completed=True
 except runtime.Stopped:logger.info('补抓已停止，未执行项保留')
 except Exception:logger.exception('补抓中断，未执行项保留，数据库失败不计入抓取次数')
 finally:
  try:
   with session_scope() as db:
    for r in db.query(Retry).filter(Retry.id.in_(ids),Retry.status=='running'):
     r.status=r.resume_status or ('manual' if r.auto_attempts>=3 else 'waiting')
    summary=f'{source_label} · {"手动" if manual else "自动"}补抓：本轮 {len(ids)} 条，已处理 {processed} 条，已恢复 {stats["recovered"]} 条，等待下轮 {stats["waiting"]} 条，需手动处理 {stats["manual"]} 条，未执行 {len(ids)-processed} 条'
    b=db.get(Batch,bid);b.status='completed' if completed else 'interrupted';b.finished_at=datetime.now(timezone.utc);b.message=summary
    b.details={**(b.details or {}),'processed':processed,'stats':stats}
   logger.info(summary)
  finally:
   runtime.local.batch_id=None
   with runtime.lock:runtime.active=None;runtime.phase='idle'
