"""Collector-owned task ledger; counts come from committed rows, never parsed log totals."""
import ast,json
from datetime import datetime,timedelta,timezone
from sqlalchemy import func,cast,or_
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import session_scope
from app.models import Article,Batch,Retry,TaskLog

def update_section(bid,section,**values):
 if not bid:return
 with session_scope() as db:
  batch=db.query(Batch).filter(Batch.id==bid).with_for_update().first()
  if not batch:return
  details=dict(batch.details or {});parts=dict(details.get('sections',{}))
  parts[section]={**parts.get(section,{}),**values};details['sections']=parts;batch.details=details

def old_sections(batch):
 # Older crawl results used Python literals rather than JSON. Never evaluate code.
 try:
  if not (batch.message or '').startswith('采集结果：'):return {}
  value=ast.literal_eval(batch.message.split('采集结果：',1)[1].split('；合并：',1)[0])
  return {r['section']:{'page':r.get('page'),'failed':r.get('fail_count',len(r.get('fail_list',[])))} for r in value}
 except (ValueError,SyntaxError,KeyError,TypeError):return {}

def records(db,batches):
 if not batches:return []
 ids=[b.id for b in batches];origin=func.coalesce(Article.origin_batch_id,Article.batch_id)
 grouped={}
 for owner,section,status,direct,count in db.query(origin,Article.section,Article.merge_status,Article.batch_id==origin,func.count()).filter(origin.in_(ids)).group_by(origin,Article.section,Article.merge_status,Article.batch_id==origin):
  p=grouped.setdefault(owner,{}).setdefault(section,{'current_added':0,'current_recovered':0,'sync':{}})
  p['current_added' if direct else 'current_recovered']+=count
  p['sync'][status or 'pending']=p['sync'].get(status or 'pending',0)+count
 retries={}
 for owner,section,status,count in db.query(Retry.source_batch_id,Retry.section,Retry.status,func.count()).filter(Retry.source_batch_id.in_(ids)).group_by(Retry.source_batch_id,Retry.section,Retry.status):
  p=retries.setdefault(owner,{}).setdefault(section,{})
  p[status]=count
 result=[]
 for b in batches:
  meta=b.details or {};saved=meta.get('sections',{});legacy=old_sections(b);parts=[]
  for section in sorted(set(saved)|set(grouped.get(b.id,{}))|set(retries.get(b.id,{}))|set(legacy)):
   snap=saved.get(section,{});current=grouped.get(b.id,{}).get(section,{});r=retries.get(b.id,{}).get(section,{})
   old=legacy.get(section,{})
   reason=snap.get('reason') or ('任务运行中' if b.status=='running' else '—')
   if reason=='正在采集' and b.status!='running':reason={'stopped':'用户停止','failed':'任务异常中断','interrupted':'服务重启中断'}.get(b.status,'—')
   parts.append({'name':section,'page':snap.get('page',old.get('page')),'reason':reason,
    'added':snap.get('added',current.get('current_added',0)),'recovered':snap.get('recovered',current.get('current_recovered',0)),
    'failed':snap.get('failed',sum(r.values()) if r else old.get('failed')),
    'remaining':sum(r.get(s,0) for s in ('waiting','running','manual')),'sync':current.get('sync',{})})
  sync={}
  for p in parts:
   for k,v in p['sync'].items():sync[k]=sync.get(k,0)+v
  result.append({'id':b.id,'name':meta.get('name') or ('CSV 导入' if b.kind=='file' else '旧库导入' if b.kind=='legacy' else '色花堂采集'),
   'kind':b.kind,'trigger':meta.get('trigger','import' if b.kind in ('file','legacy') else 'unknown'),'status':b.status,
   'create_time':b.create_time,'finished_at':b.finished_at,'added':sum(p['added'] for p in parts),
   'recovered':sum(p['recovered'] for p in parts),'failed':sum(p['failed'] for p in parts) if parts and all(p['failed'] is not None for p in parts) else None,
   'remaining':sum(p['remaining'] for p in parts),'parts':parts,'sync':sync,'message':b.message,
   'historical':not bool(meta.get('trigger'))})
 return result

def listing(page=1,page_size=10,trigger=''):
 with session_scope() as db:
  q=db.query(Batch).filter(Batch.kind.in_(['crawl','file','legacy']))
  if trigger:q=q.filter(Batch.details['trigger'].as_string()==trigger)
  total=q.count();pages=max(1,(total+page_size-1)//page_size);page=min(max(1,page),pages)
  return {'total':total,'page':page,'pages':pages,'items':records(db,q.order_by(Batch.id.desc()).offset((page-1)*page_size).limit(page_size).all())}

def detail(bid):
 with session_scope() as db:
  b=db.get(Batch,bid)
  if not b or b.kind not in ('crawl','file','legacy'):return None
  result=records(db,[b])[0]
  def related(kind):
   match=cast(Batch.details,JSONB)['source_batches'].contains([bid])
   if kind=='retry':match=or_(match,Batch.message.op('~')(rf'采集任务 #{bid}([^0-9]|$)'))
   rows=db.query(Batch).filter(Batch.kind==kind,match).order_by(Batch.id.desc()).limit(100).all()
   result=[]
   for r in rows:
    time=r.create_time
    if kind=='sync':
     try:window=json.loads(r.message or '{}').get('window')
     except (ValueError,AttributeError):window=None
     if window:
      time=datetime.fromisoformat(window)+timedelta(minutes=5)
      if datetime.now(timezone.utc)<time:continue
    result.append({'id':r.id,'create_time':time,'status':r.status,'message':r.message,'details':r.details})
   return result
  result['retries']=related('retry');result['history']=related('sync')
  result['logs']=[{'time':l.create_time,'message':l.message} for l in db.query(TaskLog).filter_by(batch_id=bid).order_by(TaskLog.id.desc()).limit(150)]
  return result
