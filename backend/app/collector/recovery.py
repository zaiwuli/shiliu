"""Database write-ahead records for parsed pages and failed-post registration."""
import json, threading, uuid
from collections import Counter
from datetime import date
from sqlalchemy.exc import OperationalError, InterfaceError
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_scope
from app.models import Article,Batch,RecoveryRecord
from app.utils.log import logger
mutex=threading.RLock()
def store(kind,payload):
 key=uuid.uuid4().hex
 with session_scope() as db:
  db.add(RecoveryRecord(id=key,kind=kind,payload=json.loads(json.dumps(payload,ensure_ascii=False,default=str))))
 return key

def apply(path):
 with session_scope() as db:
  row=db.get(RecoveryRecord,path)
  if not row:return
  content={'kind':row.kind,'payload':row.payload}
 payload=content['payload']
 if content['kind']=='failures':
  from app.collector.retry import register
  register(**payload)
 else:
  rows=payload['rows']
  for row in rows:
   if isinstance(row.get('publish_date'),str):row['publish_date']=date.fromisoformat(row['publish_date'])
  with session_scope() as db:
   created=db.execute(insert(Article).values(rows).on_conflict_do_nothing(index_elements=['tid','website']).returning(Article.batch_id,Article.origin_batch_id,Article.section)).all()
   counts=Counter((origin_id or batch_id,section,'recovered' if origin_id and origin_id!=batch_id else 'added') for batch_id,origin_id,section in created)
   for owner in sorted({key[0] for key in counts if key[0] is not None}):
    batch=db.query(Batch).filter(Batch.id==owner).with_for_update().first()
    if batch:
     details=dict(batch.details or {});parts=dict(details.get('sections',{}))
     for (bid,section,key),count in counts.items():
      if bid!=owner:continue
      part=dict(parts.get(section,{}));part[key]=part.get(key,0)+count;parts[section]=part
     details['sections']=parts;batch.details=details
  # Include already-present rows: a previous commit may have succeeded before the connection dropped.
  from app.collector.runtime import record_items
  record_items([r['tid'] for r in rows])
 with session_scope() as db:
  row=db.get(RecoveryRecord,path)
  if row:db.delete(row)

def write_page(rows):
 from app.collector.runtime import check_stop,stop
 with mutex:
  path=None
  for attempt,delay in enumerate((0,2,5,15)):
   check_stop()
   if delay and stop.wait(delay):check_stop()
   try:
    if path is None:path=store('articles',{'rows':rows})
    apply(path);return
   except (OperationalError,InterfaceError):
    logger.warning(f'数据库暂不可用，等待入库重试；尝试 {attempt+1}/4')
    if attempt==3:raise

def failures(website,section,tids):
 if not tids:return
 from app.collector.runtime import current_batch
 with mutex:
  path=store('failures',dict(website=website,section=section,tids=tids,source_batch_id=current_batch()))
  apply(path)

def replay():
 with mutex:
  with session_scope() as db:keys=[row.id for row in db.query(RecoveryRecord).order_by(RecoveryRecord.id).all()]
  for key in keys:
   logger.info('恢复数据库待入库记录')
   apply(key)
