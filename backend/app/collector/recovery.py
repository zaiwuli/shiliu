"""Durable write-ahead files for parsed pages and failed-post registration."""
import json, os, threading, uuid
from collections import Counter
from pathlib import Path
from datetime import date
from sqlalchemy.exc import OperationalError, InterfaceError
from sqlalchemy.dialects.postgresql import insert
from app.core.config import data_path
from app.core.database import session_scope
from app.models import Article,Batch
from app.utils.log import logger
mutex=threading.RLock()
root=Path(data_path)/'recovery'

def store(kind, payload):
 root.mkdir(parents=True,exist_ok=True)
 target=root/(uuid.uuid4().hex+'.json');temporary=target.with_suffix('.tmp')
 with temporary.open('w',encoding='utf-8') as stream:
  json.dump({'kind':kind,'payload':payload},stream,ensure_ascii=False,default=str);stream.flush();os.fsync(stream.fileno())
 os.replace(temporary,target)
 return target

def apply(path):
 content=json.loads(path.read_text(encoding='utf-8'));payload=content['payload']
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
 path.unlink()

def write_page(rows):
 from app.collector.runtime import check_stop,stop
 with mutex:
  path=store('articles',{'rows':rows})
  for attempt,delay in enumerate((0,2,5,15)):
   check_stop()
   if delay and stop.wait(delay):check_stop()
   try:apply(path);return
   except (OperationalError,InterfaceError):
    logger.warning(f'数据库暂不可用，保留入库缓冲；尝试 {attempt+1}/4')
    if attempt==3:raise

def failures(website,section,tids):
 if not tids:return
 from app.collector.runtime import current_batch
 with mutex:
  path=store('failures',dict(website=website,section=section,tids=tids,source_batch_id=current_batch()))
  apply(path)

def replay():
 with mutex:
  for path in sorted(root.glob('*.json')):
   logger.info('恢复本地待入库记录')
   apply(path)
